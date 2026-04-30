"""
Real LLVM backend builder using llvmlite.
"""

import base64
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

from llvmlite import binding as llvm
from llvmlite import ir

from bir.model import Extern, Field, Function, Global, Instruction, Module, Program, StructDef, Type, ValueRef


class LlvmLiteLoweringError(ValueError):
    """Raised when BIR cannot yet be lowered into real LLVM IR."""


@dataclass
class FunctionContext:
    module_name: str
    function: Function
    ir_function: ir.Function
    blocks: Dict[str, ir.Block]
    builder_by_block: Dict[str, ir.IRBuilder]
    values: Dict[str, ir.Value]
    value_types: Dict[str, Type]
    globals: Dict[str, ir.GlobalValue]
    functions: Dict[str, ir.Function]
    slot_allocas: Dict[str, ir.instructions.AllocaInstr]


class LlvmLiteProgramBuilder:
    def __init__(self, program: Program):
        self.program = program
        self.module = ir.Module(name=program.name)
        self.module.triple = _effective_target_triple(program.runtime.target_triple)
        self.struct_types: Dict[str, ir.IdentifiedStructType] = {}
        self.globals: Dict[str, ir.GlobalValue] = {}
        self.functions: Dict[str, ir.Function] = {}
        self.string_constants: Dict[str, ir.GlobalVariable] = {}

    def build(self) -> ir.Module:
        self._declare_structs()
        self._declare_globals()
        self._declare_functions()
        self._define_functions()
        self._define_runtime_entry_wrapper()
        return self.module

    def emit_object(self) -> bytes:
        llvm.initialize()
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
        module_ref = llvm.parse_assembly(str(self.module))
        module_ref.verify()
        target = llvm.Target.from_triple(self.module.triple)
        target_machine = target.create_target_machine(reloc="static", codemodel="small")
        return target_machine.emit_object(module_ref)

    def _declare_structs(self):
        for module in self.program.modules:
            for struct_def in module.structs:
                qualified = self._struct_key(module.name, struct_def.name)
                self.struct_types[qualified] = self.module.context.get_identified_type(qualified)

        for module in self.program.modules:
            for struct_def in module.structs:
                qualified = self._struct_key(module.name, struct_def.name)
                body = [self._lower_type(field.type) for field in struct_def.fields]
                self.struct_types[qualified].set_body(*body)

    def _declare_globals(self):
        for module in self.program.modules:
            for global_value in module.globals:
                ir_type = self._lower_type(global_value.type)
                name = self._qualified_symbol(module.name, global_value.name)
                global_ir = ir.GlobalVariable(self.module, ir_type, name=name)
                global_ir.linkage = "internal" if global_value.visibility == "private" else "external"
                initializer = self._global_initializer(ir_type, global_value.initializer)
                global_ir.initializer = initializer
                global_ir.global_constant = global_value.initializer is not None
                self.globals[name] = global_ir

    def _declare_functions(self):
        for module in self.program.modules:
            for extern_fn in module.externs:
                self._declare_extern(module.name, extern_fn)
            for function in module.functions:
                self._declare_function(module.name, function)

    def _declare_extern(self, module_name: str, extern_fn: Extern):
        returns = self._lower_type(extern_fn.returns)
        params = [self._lower_type(param.type) for param in extern_fn.params]
        function_type = ir.FunctionType(returns, params)
        symbol_name = extern_fn.symbol_name or extern_fn.name
        function_ir = ir.Function(self.module, function_type, name=symbol_name)
        self.functions[self._qualified_symbol(module_name, extern_fn.name)] = function_ir

    def _declare_function(self, module_name: str, function: Function):
        returns = self._lower_type(function.returns)
        params = [self._lower_type(param.type) for param in function.params]
        function_type = ir.FunctionType(returns, params)
        name = self._implementation_symbol(module_name, function.name)
        function_ir = ir.Function(self.module, function_type, name=name)
        function_ir.linkage = (
            "internal"
            if function.visibility == "private" or self._is_wrapped_entry_function(module_name, function.name)
            else "external"
        )
        for arg, param in zip(function_ir.args, function.params):
            arg.name = param.name
        self.functions[self._qualified_symbol(module_name, function.name)] = function_ir

    def _define_functions(self):
        for module in self.program.modules:
            for function in module.functions:
                context = self._create_function_context(module, function)
                for block in function.blocks:
                    self._emit_block(context, block)

    def _define_runtime_entry_wrapper(self):
        runtime = self.program.runtime
        if runtime.entry_symbol is None:
            return
        entry_function = self.functions[self._qualified_symbol(self.program.entry.module, self.program.entry.name)]
        wrapper_return = ir.VoidType() if runtime.entry_return == "void" else ir.IntType(32)
        wrapper_type = ir.FunctionType(wrapper_return, [])
        wrapper = ir.Function(self.module, wrapper_type, name=runtime.entry_symbol)
        wrapper.linkage = "external"
        builder = ir.IRBuilder(wrapper.append_basic_block("entry"))
        call_result = builder.call(entry_function, [])
        if runtime.entry_return == "void":
            builder.ret_void()
            return
        if isinstance(entry_function.function_type.return_type, ir.VoidType):
            builder.ret(ir.Constant(ir.IntType(32), 0))
            return
        builder.ret(call_result)

    def _create_function_context(self, module: Module, function: Function) -> FunctionContext:
        ir_function = self.functions[self._qualified_symbol(module.name, function.name)]
        blocks = {block.name: ir_function.append_basic_block(block.name) for block in function.blocks}
        builders = {name: ir.IRBuilder(block_ir) for name, block_ir in blocks.items()}
        value_types: Dict[str, Type] = {param.name: param.type for param in function.params}
        values: Dict[str, ir.Value] = {arg.name: arg for arg in ir_function.args}
        slot_allocas: Dict[str, ir.instructions.AllocaInstr] = {}

        entry_builder = builders[function.blocks[0].name]
        for slot_name, slot_type in self._discover_slots(function):
            alloca = entry_builder.alloca(self._lower_type(slot_type), name=slot_name)
            slot_allocas[slot_name] = alloca
            value_types[slot_name] = slot_type

        for global_value in module.globals:
            value_types[global_value.name] = global_value.type
            value_types[self._qualified_symbol(module.name, global_value.name)] = global_value.type

        for block in function.blocks:
            for instruction in block.instructions:
                if instruction.result is not None:
                    value_types[instruction.result.name] = instruction.type

        return FunctionContext(
            module_name=module.name,
            function=function,
            ir_function=ir_function,
            blocks=blocks,
            builder_by_block=builders,
            values=values,
            value_types=value_types,
            globals=self.globals,
            functions=self.functions,
            slot_allocas=slot_allocas,
        )

    def _emit_block(self, context: FunctionContext, block):
        builder = context.builder_by_block[block.name]
        for instruction in block.instructions:
            self._emit_instruction(context, builder, instruction)
        self._emit_terminator(context, builder, block.terminator)

    def _emit_instruction(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        if instruction.kind == "math":
            value = self._emit_math(context, builder, instruction)
        elif instruction.kind == "compare":
            value = self._emit_compare(context, builder, instruction)
        elif instruction.kind == "cast":
            value = self._emit_cast(context, builder, instruction)
        elif instruction.kind == "call":
            value = self._emit_call(context, builder, instruction)
        elif instruction.kind == "load":
            value = self._emit_load(context, builder, instruction)
        elif instruction.kind == "store":
            self._emit_store(context, builder, instruction)
            value = None
        elif instruction.kind == "assign":
            value = self._emit_assign(context, builder, instruction)
        elif instruction.kind == "extract":
            value = self._emit_extract(context, builder, instruction)
        elif instruction.kind == "insert":
            value = self._emit_insert(context, builder, instruction)
        elif instruction.kind == "address_of":
            value = self._emit_address_of(context, instruction)
        else:
            raise LlvmLiteLoweringError(
                f"unsupported BIR instruction kind '{instruction.kind}' in LLVM backend"
            )

        if instruction.result is not None and value is not None:
            context.values[instruction.result.name] = value

    def _emit_math(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        opcode = instruction.opcode
        if opcode is None:
            raise LlvmLiteLoweringError("math instruction missing opcode")
        if len(instruction.operands) == 1:
            operand = self._resolve_rvalue(context, builder, instruction.operands[0], instruction.type)
            if opcode == "-":
                return builder.neg(operand, name=instruction.result.name if instruction.result else "")
            if opcode == "!":
                zero = ir.Constant(operand.type, 0)
                if instruction.type.kind == "bool" or isinstance(operand.type, ir.IntType):
                    return builder.icmp_unsigned("==", operand, zero, name=instruction.result.name if instruction.result else "")
                if isinstance(operand.type, (ir.FloatType, ir.DoubleType)):
                    return builder.fcmp_ordered("==", operand, zero, name=instruction.result.name if instruction.result else "")
                raise LlvmLiteLoweringError("logical not requires an integer, boolean, or floating-point operand")
            if opcode == "~":
                all_ones = ir.Constant(operand.type, -1)
                return builder.xor(operand, all_ones, name=instruction.result.name if instruction.result else "")
            raise LlvmLiteLoweringError(f"unsupported unary opcode '{opcode}' in LLVM backend")

        left = self._resolve_rvalue(context, builder, instruction.operands[0], instruction.type)
        right = self._resolve_rvalue(context, builder, instruction.operands[1], instruction.type)
        kind = instruction.type.kind

        if opcode == "+":
            return builder.fadd(left, right) if kind in {"f32", "f64"} else builder.add(left, right)
        if opcode == "-":
            return builder.fsub(left, right) if kind in {"f32", "f64"} else builder.sub(left, right)
        if opcode == "*":
            return builder.fmul(left, right) if kind in {"f32", "f64"} else builder.mul(left, right)
        if opcode == "/":
            if kind in {"f32", "f64"}:
                return builder.fdiv(left, right)
            return builder.udiv(left, right) if kind.startswith("u") else builder.sdiv(left, right)
        if opcode == "%":
            if kind in {"f32", "f64"}:
                return builder.frem(left, right)
            return builder.urem(left, right) if kind.startswith("u") else builder.srem(left, right)
        if opcode == "&":
            return builder.and_(left, right)
        if opcode == "|":
            return builder.or_(left, right)
        if opcode == "^":
            return builder.xor(left, right)
        if opcode == "<<":
            return builder.shl(left, right)
        if opcode == ">>":
            return builder.lshr(left, right) if kind.startswith("u") else builder.ashr(left, right)
        raise LlvmLiteLoweringError(f"unsupported binary opcode '{opcode}' in LLVM backend")

    def _emit_compare(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        opcode = instruction.opcode or "=="
        operand_type = context.value_types.get(instruction.operands[0].name, instruction.type)
        left = self._resolve_rvalue(context, builder, instruction.operands[0], operand_type)
        right = self._resolve_rvalue(context, builder, instruction.operands[1], operand_type)
        if operand_type.kind in {"f32", "f64"}:
            predicate_map = {
                "==": "==",
                "!=": "!=",
                "<": "<",
                "<=": "<=",
                ">": ">",
                ">=": ">=",
            }
            return builder.fcmp_ordered(predicate_map[opcode], left, right)

        predicate_map = {
            "==": "==",
            "!=": "!=",
            "<": "<",
            "<=": "<=",
            ">": ">",
            ">=": ">=",
        }
        if operand_type.kind.startswith("u") or operand_type.kind == "bool":
            return builder.icmp_unsigned(predicate_map[opcode], left, right)
        return builder.icmp_signed(predicate_map[opcode], left, right)

    def _emit_cast(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        source_ref = instruction.operands[0]
        source_type = context.value_types.get(source_ref.name)
        if source_type is None and source_ref.name.startswith("literal_"):
            source_type = _type_for_literal_name(source_ref.name)
        if source_type is None:
            raise LlvmLiteLoweringError(f"missing source type for cast operand '{source_ref.name}'")
        value = self._resolve_rvalue(context, builder, source_ref, source_type)
        target_type = self._lower_type(instruction.type)
        return _cast_value(builder, value, source_type, instruction.type, target_type)

    def _emit_call(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        callee_name = instruction.opcode
        if callee_name is None:
            raise LlvmLiteLoweringError("call instruction missing callee")
        function_ref = self.functions.get(self._qualified_symbol(context.module_name, callee_name))
        if function_ref is None:
            function_ref = self.functions.get(callee_name)
        if function_ref is None:
            raise LlvmLiteLoweringError(f"unknown call target '{callee_name}'")
        arg_types = [context.value_types.get(arg.name) for arg in instruction.operands[1:]]
        args = [
            self._resolve_rvalue(context, builder, arg, arg_type)
            for arg, arg_type in zip(instruction.operands[1:], arg_types)
        ]
        call = builder.call(function_ref, args)
        if isinstance(function_ref.function_type.return_type, ir.VoidType):
            return None
        return call

    def _emit_load(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        source_ref = instruction.operands[0]
        if instruction.opcode == "*":
            pointer_value = self._resolve_rvalue(context, builder, source_ref, context.value_types.get(source_ref.name))
            return builder.load(pointer_value)
        pointer = self._resolve_storage(context, source_ref)
        return builder.load(pointer)

    def _emit_store(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        value = self._resolve_rvalue(context, builder, instruction.operands[1], instruction.type)
        target_ref = instruction.operands[0]
        if instruction.opcode in {"*=", "field_store"}:
            pointer = self._resolve_rvalue(context, builder, target_ref, context.value_types.get(target_ref.name))
        else:
            pointer = self._resolve_storage(context, target_ref)
        builder.store(value, pointer)

    def _emit_assign(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        if instruction.opcode == "array_literal":
            return ir.Constant(self._lower_type(instruction.type), None)
        if instruction.opcode == "array_repeat":
            if instruction.type.kind != "array" or instruction.type.len is None or instruction.type.elem is None:
                raise LlvmLiteLoweringError("array_repeat requires concrete array type")
            element_type = instruction.type.elem
            element_value = self._resolve_rvalue(context, builder, instruction.operands[0], element_type)
            aggregate = ir.Constant(self._lower_type(instruction.type), None)
            for index in range(instruction.type.len):
                aggregate = builder.insert_value(aggregate, element_value, index)
            return aggregate
        if instruction.opcode and instruction.opcode.startswith("struct_literal:"):
            return ir.Constant(self._lower_type(instruction.type), None)
        raise LlvmLiteLoweringError(f"unsupported assign opcode '{instruction.opcode}' in LLVM backend")

    def _emit_extract(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        base = self._resolve_rvalue(context, builder, instruction.operands[0], context.value_types.get(instruction.operands[0].name))
        if instruction.opcode == "index":
            index = _literal_index(instruction.operands[1])
            if index is None:
                raise LlvmLiteLoweringError("dynamic aggregate indexing is not supported in the real LLVM backend yet")
            return builder.extract_value(base, index)
        field_index = self._field_index(context.value_types[instruction.operands[0].name], instruction.opcode)
        return builder.extract_value(base, field_index)

    def _emit_insert(self, context: FunctionContext, builder: ir.IRBuilder, instruction: Instruction):
        base = self._resolve_rvalue(context, builder, instruction.operands[0], instruction.type)
        if instruction.opcode == "index":
            index = _literal_index(instruction.operands[1])
            if index is None:
                raise LlvmLiteLoweringError("dynamic aggregate indexing is not supported in the real LLVM backend yet")
            value = self._resolve_rvalue(
                context,
                builder,
                instruction.operands[2],
                instruction.type.elem if instruction.type.elem is not None else context.value_types.get(instruction.operands[2].name),
            )
            return builder.insert_value(base, value, index)
        field_index = self._field_index(instruction.type, instruction.opcode)
        value = self._resolve_rvalue(
            context,
            builder,
            instruction.operands[1],
            _field_type(instruction.type, instruction.opcode),
        )
        return builder.insert_value(base, value, field_index)

    def _emit_address_of(self, context: FunctionContext, instruction: Instruction):
        operand = instruction.operands[0]
        return self._resolve_storage(context, operand)

    def _emit_terminator(self, context: FunctionContext, builder: ir.IRBuilder, terminator):
        if builder.block.is_terminated:
            return
        if terminator.kind == "ret":
            if terminator.operands:
                value_type = context.value_types.get(terminator.operands[0].name, context.function.returns)
                value = self._resolve_rvalue(context, builder, terminator.operands[0], value_type)
                builder.ret(value)
            else:
                builder.ret_void()
            return
        if terminator.kind == "br":
            builder.branch(context.blocks[terminator.targets[0]])
            return
        if terminator.kind == "cond_br":
            condition = self._resolve_rvalue(context, builder, terminator.operands[0], Type(kind="bool"))
            builder.cbranch(condition, context.blocks[terminator.targets[0]], context.blocks[terminator.targets[1]])
            return
        if terminator.kind == "unreachable":
            builder.unreachable()
            return
        raise LlvmLiteLoweringError(f"unsupported terminator kind '{terminator.kind}' in LLVM backend")

    def _resolve_rvalue(
        self,
        context: FunctionContext,
        builder: ir.IRBuilder,
        ref: ValueRef,
        expected_type: Optional[Type],
    ) -> ir.Value:
        name = ref.name
        if name in context.values:
            return context.values[name]
        if name in context.slot_allocas:
            return builder.load(context.slot_allocas[name])
        qualified_global = self._qualified_symbol(context.module_name, name)
        if qualified_global in context.globals:
            return builder.load(context.globals[qualified_global])
        if name in context.globals:
            return builder.load(context.globals[name])
        if name.startswith("literal_"):
            return self._literal_value(name, expected_type)
        raise LlvmLiteLoweringError(f"unable to resolve value '{name}' in LLVM backend")

    def _resolve_storage(self, context: FunctionContext, ref: ValueRef):
        name = ref.name
        if name in context.slot_allocas:
            return context.slot_allocas[name]
        qualified_global = self._qualified_symbol(context.module_name, name)
        if qualified_global in context.globals:
            return context.globals[qualified_global]
        if name in context.globals:
            return context.globals[name]
        if name in context.values:
            return context.values[name]
        raise LlvmLiteLoweringError(f"unable to resolve storage location '{name}' in LLVM backend")

    def _literal_value(self, literal_name: str, expected_type: Optional[Type]) -> ir.Value:
        if literal_name.startswith("literal_string_b64_"):
            encoded = literal_name[len("literal_string_b64_") :]
            padding = "=" * ((4 - len(encoded) % 4) % 4)
            text = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
            return self._string_constant(text)

        _, literal_kind, raw_value = literal_name.split("_", 2)
        value_text = raw_value.replace("neg_", "-")
        if literal_kind == "bool":
            return ir.Constant(ir.IntType(1), 1 if raw_value == "true" else 0)

        target_type = self._lower_type(expected_type or _infer_literal_type(literal_kind))
        if isinstance(target_type, ir.IntType):
            return ir.Constant(target_type, int(value_text, 0))
        if isinstance(target_type, ir.FloatType) or isinstance(target_type, ir.DoubleType):
            return ir.Constant(target_type, float(value_text))
        raise LlvmLiteLoweringError(f"unsupported literal '{literal_name}' for target type '{target_type}'")

    def _string_constant(self, text: str) -> ir.Value:
        if text in self.string_constants:
            global_ir = self.string_constants[text]
        else:
            data = bytearray(text.encode("utf-8") + b"\x00")
            const_type = ir.ArrayType(ir.IntType(8), len(data))
            global_ir = ir.GlobalVariable(self.module, const_type, name=f".str.{len(self.string_constants)}")
            global_ir.linkage = "internal"
            global_ir.global_constant = True
            global_ir.initializer = ir.Constant(const_type, data)
            self.string_constants[text] = global_ir
        zero = ir.Constant(ir.IntType(32), 0)
        return global_ir.gep([zero, zero])

    def _discover_slots(self, function: Function) -> List[tuple[str, Type]]:
        slots: Dict[str, Type] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if instruction.kind in {"store", "load"} and instruction.operands:
                    target = instruction.operands[0].name
                    if target.startswith("slot_"):
                        slots.setdefault(target, instruction.type)
        return list(slots.items())

    def _global_initializer(self, ir_type, initializer: Optional[str]):
        if initializer is None:
            return ir.Constant(ir_type, None)
        text = initializer.strip()
        if isinstance(ir_type, ir.IntType):
            if text.lower() in {"true", "false"}:
                return ir.Constant(ir_type, 1 if text.lower() == "true" else 0)
            return ir.Constant(ir_type, int(text, 0))
        if isinstance(ir_type, ir.FloatType) or isinstance(ir_type, ir.DoubleType):
            return ir.Constant(ir_type, float(text))
        return ir.Constant(ir_type, None)

    def _lower_type(self, type_node: Type):
        scalar_map = {
            "int": ir.IntType(32),
            "uint": ir.IntType(32),
            "i8": ir.IntType(8),
            "i16": ir.IntType(16),
            "i32": ir.IntType(32),
            "i64": ir.IntType(64),
            "u8": ir.IntType(8),
            "u16": ir.IntType(16),
            "u32": ir.IntType(32),
            "u64": ir.IntType(64),
            "bool": ir.IntType(1),
            "f32": ir.FloatType(),
            "f64": ir.DoubleType(),
            "void": ir.VoidType(),
        }
        if type_node.kind in scalar_map:
            return scalar_map[type_node.kind]
        if type_node.kind == "ptr":
            if type_node.elem is None:
                raise LlvmLiteLoweringError("pointer type missing element")
            return self._lower_type(type_node.elem).as_pointer()
        if type_node.kind == "array":
            if type_node.elem is None or type_node.len is None:
                raise LlvmLiteLoweringError("array type missing shape")
            return ir.ArrayType(self._lower_type(type_node.elem), type_node.len)
        if type_node.kind == "struct":
            if not type_node.name:
                raise LlvmLiteLoweringError("struct type missing name")
            qualified = self._lookup_struct_key(type_node.name)
            struct_type = self.struct_types.get(qualified)
            if struct_type is None:
                raise LlvmLiteLoweringError(f"unknown struct type '{type_node.name}'")
            return struct_type
        raise LlvmLiteLoweringError(f"unsupported BIR type '{type_node.kind}' in LLVM backend")

    def _lookup_struct_key(self, struct_name: str) -> str:
        for key in self.struct_types:
            if key.endswith(f".{struct_name}"):
                return key
        raise LlvmLiteLoweringError(f"unknown struct '{struct_name}'")

    def _field_index(self, base_type: Type, field_name: str) -> int:
        for index, field in enumerate(base_type.fields):
            if field.name == field_name:
                return index
        raise LlvmLiteLoweringError(f"unknown field '{field_name}'")

    def _qualified_symbol(self, module_name: str, name: str) -> str:
        return f"{module_name}.{name}"

    def _implementation_symbol(self, module_name: str, name: str) -> str:
        if self._is_wrapped_entry_function(module_name, name):
            return self.program.runtime.internal_entry_symbol
        return self._qualified_symbol(module_name, name)

    def _is_wrapped_entry_function(self, module_name: str, name: str) -> bool:
        return (
            self.program.runtime.entry_symbol is not None
            and self.program.entry.module == module_name
            and self.program.entry.name == name
        )

    def _struct_key(self, module_name: str, name: str) -> str:
        return f"{module_name}.{name}"


def _field_type(base_type: Type, field_name: str) -> Type:
    for field in base_type.fields:
        if field.name == field_name:
            return field.type
    raise LlvmLiteLoweringError(f"unknown field '{field_name}'")


def _literal_index(ref: ValueRef) -> Optional[int]:
    if ref.name.startswith("literal_i32_"):
        return int(ref.name[len("literal_i32_") :].replace("neg_", "-"))
    if ref.name.startswith("literal_u32_"):
        return int(ref.name[len("literal_u32_") :].replace("neg_", "-"))
    return None


def _infer_literal_type(kind: str) -> Type:
    if kind == "bool":
        return Type(kind="bool")
    if kind.startswith("u"):
        return Type(kind=kind)
    if kind.startswith("i"):
        return Type(kind=kind)
    if kind.startswith("f"):
        return Type(kind=kind)
    if kind == "int":
        return Type(kind="i32")
    if kind == "float":
        return Type(kind="f64")
    raise LlvmLiteLoweringError(f"cannot infer literal type '{kind}'")


def _type_for_literal_name(literal_name: str) -> Type:
    if not literal_name.startswith("literal_"):
        raise LlvmLiteLoweringError(f"cannot infer non-literal operand type for '{literal_name}'")
    _, literal_kind, _ = literal_name.split("_", 2)
    return _infer_literal_type(literal_kind)


def _cast_value(builder: ir.IRBuilder, value: ir.Value, source_type: Type, target_type: Type, target_ir):
    source_ir = value.type
    if source_type.kind == target_type.kind:
        return value
    if source_type.kind == "ptr" and target_type.kind == "ptr":
        return builder.bitcast(value, target_ir)
    if source_type.kind == "ptr" and target_type.kind in {"i32", "i64", "u32", "u64"}:
        return builder.ptrtoint(value, target_ir)
    if target_type.kind == "ptr" and source_type.kind in {"i32", "i64", "u32", "u64"}:
        return builder.inttoptr(value, target_ir)
    if source_type.kind.startswith(("i", "u", "bool")) and target_type.kind.startswith(("i", "u", "bool")):
        source_bits = source_ir.width
        target_bits = target_ir.width
        if source_bits < target_bits:
            return builder.zext(value, target_ir) if source_type.kind.startswith("u") or source_type.kind == "bool" else builder.sext(value, target_ir)
        if source_bits > target_bits:
            return builder.trunc(value, target_ir)
        return builder.bitcast(value, target_ir)
    if source_type.kind in {"f32", "f64"} and target_type.kind in {"f32", "f64"}:
        if source_type.kind == "f32" and target_type.kind == "f64":
            return builder.fpext(value, target_ir)
        if source_type.kind == "f64" and target_type.kind == "f32":
            return builder.fptrunc(value, target_ir)
    if source_type.kind.startswith(("i", "u", "bool")) and target_type.kind in {"f32", "f64"}:
        return builder.uitofp(value, target_ir) if source_type.kind.startswith("u") or source_type.kind == "bool" else builder.sitofp(value, target_ir)
    if source_type.kind in {"f32", "f64"} and target_type.kind.startswith(("i", "u", "bool")):
        return builder.fptoui(value, target_ir) if target_type.kind.startswith("u") or target_type.kind == "bool" else builder.fptosi(value, target_ir)
    raise LlvmLiteLoweringError(f"unsupported cast from '{source_type.kind}' to '{target_type.kind}'")


def _effective_target_triple(target_triple: str) -> str:
    if target_triple == "native":
        return _native_host_triple()
    return target_triple


@lru_cache(maxsize=1)
def _native_host_triple() -> str:
    llvm.initialize()
    llvm.initialize_native_target()
    default_triple = llvm.get_default_triple()
    if default_triple.endswith("windows-msvc"):
        gcc_triple = _probe_gcc_triple()
        if gcc_triple:
            return gcc_triple
    return default_triple


@lru_cache(maxsize=1)
def _probe_gcc_triple() -> Optional[str]:
    try:
        result = subprocess.run(
            ["gcc", "-dumpmachine"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    triple = (result.stdout or "").strip()
    return triple or None
