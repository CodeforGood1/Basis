"""
BASIS Parser - Recursive Descent Parser
Converts token stream into Abstract Syntax Tree (AST).
"""

from lexer import Token, TokenType
from diagnostics import DiagnosticEngine
from ast_defs import (
    SourceSpan, Module, Param, FunctionDecl, StructField, StructDecl,
    LetDecl, ConstDecl, ImportDecl, ExternStaticDecl, Annotation,
    TypeName, PointerType, ArrayType, VolatileType,
    Block, ReturnStmt, IfStmt, ElifBranch, ForStmt, WhileStmt, BreakStmt, ContinueStmt, ExprStmt,
    IdentifierExpr, LiteralExpr, BinaryExpr, UnaryExpr, CallExpr, IndexExpr,
    FieldAccessExpr, AssignmentExpr, AddressOfExpr, DereferenceExpr, CastExpr,
    ArrayLiteralExpr, ArrayRepeatExpr, ArrayOverride, StructLiteralExpr, FieldInit, print_ast
)


class Parser:
    """Recursive descent parser for BASIS."""
    
    def __init__(self, tokens, filename="<input>", diag_engine=None):
        self.tokens = tokens
        self.filename = filename
        self.diag = diag_engine or DiagnosticEngine()
        self.pos = 0
    
    # ========================================================================
    # Token Management
    # ========================================================================
    
    def current(self):
        """Get current token without consuming."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF
    
    def peek(self, offset=1):
        """Look ahead at token."""
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF
    
    def previous(self):
        """Get the previous token (last consumed)."""
        if self.pos > 0:
            return self.tokens[self.pos - 1]
        return self.tokens[0]
    
    def advance(self):
        """Consume current token and move to next. Returns the consumed token."""
        token = self.current()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return token
    
    def expect(self, token_type, context=""):
        """Expect a specific token type and consume it."""
        token = self.current()
        if token.type != token_type:
            ctx_msg = f" in {context}" if context else ""
            self.diag.error(
                'ERR_PARSE_EXPECTED_TOKEN',
                f"expected {token_type.name}, found {token.type.name}{ctx_msg}",
                token.line, token.column, token.length,
                self.filename
            )
            return None
        self.advance()
        return token
    
    def match(self, *token_types):
        """Check if current token matches any of the given types."""
        return self.current().type in token_types
    
    def consume(self, token_type):
        """Consume token if it matches type, otherwise return None."""
        if self.match(token_type):
            token = self.current()
            self.advance()
            return token
        return None
    
    def at_eof(self):
        """Check if at end of file."""
        return self.current().type == TokenType.EOF
    
    def make_span(self, start_token, end_token=None):
        """Create a SourceSpan from tokens."""
        if end_token is None:
            end_token = start_token
        return SourceSpan(
            start_token.line, start_token.column,
            end_token.line, end_token.column + end_token.length
        )
    
    # ========================================================================
    # Error Recovery
    # ========================================================================
    
    def synchronize(self):
        """Skip tokens until we reach a safe synchronization point."""
        while not self.at_eof():
            # Stop at statement/declaration boundaries
            if self.match(TokenType.SEMICOLON):
                self.advance()
                return
            
            if self.match(TokenType.RBRACE):
                return
            
            # Keywords that start declarations
            if self.match(TokenType.FN, TokenType.STRUCT, TokenType.LET,
                         TokenType.CONST, TokenType.EXTERN, TokenType.IMPORT,
                         TokenType.PUBLIC, TokenType.PRIVATE):
                return
            
            self.advance()
    
    # ========================================================================
    # Top-Level Parsing
    # ========================================================================
    
    def parse(self, module_name):
        """Parse entire module."""
        declarations = []
        max_memory_bytes = None
        
        # Parse optional module-level directives first
        while self.match(TokenType.HASH):
            directive_result = self._parse_directive()
            if directive_result:
                directive_name, directive_value = directive_result
                if directive_name == "max_memory":
                    if max_memory_bytes is not None:
                        token = self.current()
                        self.diag.error(
                            'ERR_PARSE_DUPLICATE_DIRECTIVE',
                            "duplicate #[max_memory] directive",
                            token.line, token.column, 1,
                            self.filename
                        )
                    else:
                        max_memory_bytes = directive_value
        
        while not self.at_eof():
            # Check for misplaced directive (must be at top of file)
            if self.match(TokenType.HASH):
                token = self.current()
                self.diag.error(
                    'ERR_PARSE_DIRECTIVE_POSITION',
                    "#[max_memory] directive must appear at the start of the file",
                    token.line, token.column, 1,
                    self.filename
                )
                self._parse_directive()  # consume it anyway
                continue
                
            try:
                decl = self.parse_declaration()
                if decl:
                    declarations.append(decl)
            except Exception as e:
                # Unexpected error - report and try to recover
                token = self.current()
                self.diag.error(
                    'ERR_PARSE_INTERNAL',
                    f"internal parser error: {e}",
                    token.line, token.column, 1,
                    self.filename
                )
                self.synchronize()
        
        # Create module with span covering entire source
        if declarations:
            start_span = declarations[0].span
            end_span = declarations[-1].span
            span = SourceSpan(
                start_span.start_line, start_span.start_col,
                end_span.end_line, end_span.end_col
            )
        else:
            span = SourceSpan(1, 1, 1, 1)
        
        return Module(span, module_name, declarations, max_memory_bytes)
    
    def _parse_directive(self):
        """Parse a #[directive(value)] construct. Returns (name, value) or None."""
        if not self.consume(TokenType.HASH):
            return None
        
        if not self.consume(TokenType.LBRACKET):
            token = self.current()
            self.diag.error(
                'ERR_PARSE_DIRECTIVE',
                "expected '[' after '#' in directive",
                token.line, token.column, 1,
                self.filename
            )
            return None
        
        # Get directive name
        name_token = self.consume(TokenType.IDENTIFIER)
        if not name_token:
            token = self.current()
            self.diag.error(
                'ERR_PARSE_DIRECTIVE',
                "expected directive name",
                token.line, token.column, 1,
                self.filename
            )
            return None
        
        directive_name = name_token.lexeme
        
        # Expect (value)
        if not self.consume(TokenType.LPAREN):
            token = self.current()
            self.diag.error(
                'ERR_PARSE_DIRECTIVE',
                f"expected '(' after directive name '{directive_name}'",
                token.line, token.column, 1,
                self.filename
            )
            return None
        
        # Parse the value - for max_memory, expect a size like 256kb or 1mb
        value_token = self.current()
        if not self.match(TokenType.INTEGER, TokenType.IDENTIFIER):
            self.diag.error(
                'ERR_PARSE_DIRECTIVE',
                f"expected size value in directive",
                value_token.line, value_token.column, 1,
                self.filename
            )
            return None
        
        # Parse size value
        directive_value = self._parse_memory_size()
        if directive_value is None:
            return None
        
        if not self.consume(TokenType.RPAREN):
            token = self.current()
            self.diag.error(
                'ERR_PARSE_DIRECTIVE',
                "expected ')' after directive value",
                token.line, token.column, 1,
                self.filename
            )
            return None
        
        if not self.consume(TokenType.RBRACKET):
            token = self.current()
            self.diag.error(
                'ERR_PARSE_DIRECTIVE',
                "expected ']' to close directive",
                token.line, token.column, 1,
                self.filename
            )
            return None
        
        return (directive_name, directive_value)
    
    def _parse_memory_size(self):
        """Parse a memory size like 256kb, 1mb, 2048. Returns bytes as int."""
        # Can be: INTEGER or INTEGER followed by unit identifier
        # Actually: "256kb" would be lexed as INTEGER(256) + IDENTIFIER(kb)
        
        if self.match(TokenType.INTEGER):
            num_token = self.current()
            self.advance()
            value = int(num_token.lexeme)
            
            # Check for optional unit suffix
            if self.match(TokenType.IDENTIFIER):
                unit_token = self.current()
                unit = unit_token.lexeme.lower()
                
                if unit in ('b', 'bytes'):
                    self.advance()
                    return value
                elif unit in ('kb', 'k'):
                    self.advance()
                    return value * 1024
                elif unit in ('mb', 'm'):
                    self.advance()
                    return value * 1024 * 1024
                # No unit - just raw bytes
            
            return value
        
        token = self.current()
        self.diag.error(
            'ERR_PARSE_DIRECTIVE',
            f"expected memory size (e.g., 256kb, 1mb, 2048)",
            token.line, token.column, 1,
            self.filename
        )
        return None
    
    def _parse_annotation(self):
        """Parse @name or @name(args) annotation."""
        start_token = self.current()
        self.expect(TokenType.AT, "annotation")
        
        name_token = self.expect(TokenType.IDENTIFIER, "annotation name")
        if not name_token:
            return None
        
        ann_name = name_token.lexeme
        arguments = {}
        positional_index = 0
        
        # Optional arguments: @name(arg1, key=val, ...)
        if self.match(TokenType.LPAREN):
            self.advance()
            while not self.match(TokenType.RPAREN) and not self.at_eof():
                # Support named args like max=10
                if self.match(TokenType.IDENTIFIER) and self.peek().type == TokenType.EQ:
                    arg_name = self.current().lexeme
                    self.advance()  # skip name
                    self.advance()  # skip =
                    arg_val = self.parse_expression()
                    if arg_val:
                        arguments[arg_name] = arg_val
                else:
                    # Positional argument — store as 'value' for first, or indexed
                    arg_val = self.parse_expression()
                    if arg_val:
                        key = 'value' if positional_index == 0 else f'arg{positional_index}'
                        arguments[key] = arg_val
                        positional_index += 1
                
                if not self.match(TokenType.RPAREN):
                    if not self.consume(TokenType.COMMA):
                        break
            
            self.expect(TokenType.RPAREN, "annotation arguments")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        return Annotation(span, ann_name, arguments)
    
    # ========================================================================
    # Declaration Parsing
    # ========================================================================
    
    def parse_declaration(self):
        """Parse top-level declaration."""
        # Collect leading annotations
        leading_annotations = []
        while self.match(TokenType.AT):
            annotation = self._parse_annotation()
            if annotation:
                leading_annotations.append(annotation)
        
        # Check for visibility modifiers
        visibility = None
        if self.match(TokenType.PUBLIC, TokenType.PRIVATE):
            visibility = self.current().lexeme
            self.advance()
        
        # Parse declaration based on keyword
        if self.match(TokenType.FN):
            decl = self.parse_function(visibility, is_extern=False)
            if decl and leading_annotations:
                decl.annotations = leading_annotations + decl.annotations
            return decl
        
        elif self.match(TokenType.EXTERN):
            self.advance()
            if self.match(TokenType.FN):
                decl = self.parse_function(visibility, is_extern=True)
                if decl and leading_annotations:
                    decl.annotations = leading_annotations + decl.annotations
                return decl
            elif self.match(TokenType.STATIC):
                return self.parse_extern_static()
            else:
                self.diag.error(
                    'ERR_PARSE_EXPECTED_TOKEN',
                    "expected 'fn' or 'static' after 'extern'",
                    self.current().line, self.current().column, 1,
                    self.filename
                )
                self.synchronize()
                return None
        
        elif self.match(TokenType.STRUCT):
            decl = self.parse_struct(visibility)
            if decl and leading_annotations:
                decl.annotations = leading_annotations + decl.annotations
            return decl
        
        elif self.match(TokenType.CONST):
            return self.parse_const(visibility)
        
        elif self.match(TokenType.LET):
            # Top-level let (static variable)
            return self.parse_let()
        
        elif self.match(TokenType.IMPORT):
            return self.parse_import()
        
        else:
            token = self.current()
            self.diag.error(
                'ERR_PARSE_EXPECTED_TOKEN',
                f"expected declaration, found {token.type.name}",
                token.line, token.column, token.length,
                self.filename
            )
            self.synchronize()
            return None
    
    def parse_function(self, visibility, is_extern):
        """Parse function declaration."""
        start_token = self.current()
        self.expect(TokenType.FN, "function declaration")
        
        # Function name
        name_token = self.expect(TokenType.IDENTIFIER, "function name")
        if not name_token:
            self.synchronize()
            return None
        name = name_token.lexeme
        
        # Parameters
        self.expect(TokenType.LPAREN, "function parameters")
        params = []
        
        while not self.match(TokenType.RPAREN) and not self.at_eof():
            param = self.parse_parameter()
            if param:
                params.append(param)
            
            if not self.match(TokenType.RPAREN):
                if not self.consume(TokenType.COMMA):
                    self.diag.error(
                        'ERR_PARSE_EXPECTED_TOKEN',
                        "expected ',' or ')' in parameter list",
                        self.current().line, self.current().column, 1,
                        self.filename
                    )
                    break
        
        self.expect(TokenType.RPAREN, "function parameters")
        
        # Return type
        self.expect(TokenType.ARROW, "function return type")
        return_type = self.parse_type()
        
        # Annotations (e.g., @recursion(max=10), @stack(256), @align(4))
        annotations = []
        while self.match(TokenType.AT):
            annotation = self._parse_annotation()
            if annotation:
                annotations.append(annotation)
        
        # Check for extern symbol alias
        extern_symbol = None
        if is_extern and self.match(TokenType.EQ):
            self.advance()
            symbol_token = self.expect(TokenType.STRING, "extern symbol name")
            if symbol_token:
                extern_symbol = symbol_token.lexeme
        
        # Function body
        body = None
        if is_extern:
            # Extern functions have no body
            self.expect(TokenType.SEMICOLON, "extern function")
        elif self.match(TokenType.EQ):
            # Expression body: fn foo() -> T = expr;
            self.advance()
            expr = self.parse_expression()
            if expr:
                body = Block(self.make_span(start_token, self.current()),
                           [ReturnStmt(self.make_span(start_token, self.current()), expr)])
            self.expect(TokenType.SEMICOLON, "expression function")
        elif self.match(TokenType.LBRACE):
            # Block body
            body = self.parse_block()
        else:
            self.diag.error(
                'ERR_PARSE_EXPECTED_TOKEN',
                "expected function body or ';' for extern",
                self.current().line, self.current().column, 1,
                self.filename
            )
        
        end_token = self.tokens[self.pos - 1] if self.pos > 0 else start_token
        span = self.make_span(start_token, end_token)
        
        return FunctionDecl(span, name, params, return_type, body, is_extern,
                           visibility, annotations, extern_symbol)
    
    def parse_parameter(self):
        """Parse function parameter."""
        start_token = self.current()
        
        name_token = self.expect(TokenType.IDENTIFIER, "parameter name")
        if not name_token:
            return None
        
        self.expect(TokenType.COLON, "parameter type")
        param_type = self.parse_type()
        
        span = self.make_span(start_token, self.tokens[self.pos - 1])
        return Param(span, name_token.lexeme, param_type)
    
    def parse_struct(self, visibility):
        """Parse struct declaration."""
        start_token = self.current()
        self.expect(TokenType.STRUCT, "struct declaration")
        
        name_token = self.expect(TokenType.IDENTIFIER, "struct name")
        if not name_token:
            self.synchronize()
            return None
        
        # Annotations (e.g., @align(4), @packed)
        annotations = []
        while self.match(TokenType.AT):
            annotation = self._parse_annotation()
            if annotation:
                annotations.append(annotation)
        
        self.expect(TokenType.LBRACE, "struct body")
        
        fields = []
        while not self.match(TokenType.RBRACE) and not self.at_eof():
            field = self.parse_struct_field()
            if field:
                fields.append(field)
            
            # Fields can be separated by comma or semicolon (optional)
            self.consume(TokenType.COMMA)
        
        self.expect(TokenType.RBRACE, "struct body")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return StructDecl(span, name_token.lexeme, fields, visibility, annotations)
    
    def parse_struct_field(self):
        """Parse struct field."""
        start_token = self.current()
        
        name_token = self.expect(TokenType.IDENTIFIER, "field name")
        if not name_token:
            return None
        
        self.expect(TokenType.COLON, "field type")
        field_type = self.parse_type()
        
        span = self.make_span(start_token, self.tokens[self.pos - 1])
        return StructField(span, name_token.lexeme, field_type)
    
    def parse_const(self, visibility):
        """Parse const declaration."""
        start_token = self.current()
        self.expect(TokenType.CONST, "const declaration")
        
        name_token = self.expect(TokenType.IDENTIFIER, "const name")
        if not name_token:
            self.synchronize()
            return None
        
        self.expect(TokenType.COLON, "const type")
        const_type = self.parse_type()
        
        self.expect(TokenType.EQ, "const value")
        value = self.parse_expression()
        
        self.expect(TokenType.SEMICOLON, "const declaration")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return ConstDecl(span, name_token.lexeme, const_type, value, visibility)
    
    def parse_let(self):
        """Parse let declaration."""
        start_token = self.current()
        self.expect(TokenType.LET, "let declaration")
        
        name_token = self.expect(TokenType.IDENTIFIER, "variable name")
        if not name_token:
            self.synchronize()
            return None
        
        self.expect(TokenType.COLON, "variable type")
        var_type = self.parse_type()
        
        # Optional initializer
        initializer = None
        if self.match(TokenType.EQ):
            self.advance()
            initializer = self.parse_expression()
        
        self.expect(TokenType.SEMICOLON, "let declaration")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return LetDecl(span, name_token.lexeme, var_type, initializer)
    
    def parse_import(self):
        """Parse import declaration."""
        start_token = self.current()
        self.expect(TokenType.IMPORT, "import declaration")
        
        module_token = self.expect(TokenType.IDENTIFIER, "module name")
        if not module_token:
            self.synchronize()
            return None
        
        module_name = module_token.lexeme
        items = None
        is_wildcard = False
        
        # Check for :: notation
        if self.match(TokenType.COLON):
            self.advance()
            self.expect(TokenType.COLON, "import path")
            
            if self.match(TokenType.STAR):
                # import mod::*
                self.advance()
                is_wildcard = True
            elif self.match(TokenType.LBRACE):
                # import mod::{a, b, c}
                self.advance()
                items = []
                
                while not self.match(TokenType.RBRACE) and not self.at_eof():
                    item_token = self.expect(TokenType.IDENTIFIER, "import item")
                    if item_token:
                        items.append(item_token.lexeme)
                    
                    if not self.match(TokenType.RBRACE):
                        if not self.consume(TokenType.COMMA):
                            break
                
                self.expect(TokenType.RBRACE, "import list")
        
        self.expect(TokenType.SEMICOLON, "import declaration")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return ImportDecl(span, module_name, items, is_wildcard)
    
    def parse_extern_static(self):
        """Parse extern static declaration."""
        start_token = self.current()
        self.expect(TokenType.STATIC, "extern static")
        
        name_token = self.expect(TokenType.IDENTIFIER, "static name")
        if not name_token:
            self.synchronize()
            return None
        
        self.expect(TokenType.COLON, "static type")
        static_type = self.parse_type()
        
        self.expect(TokenType.SEMICOLON, "extern static")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return ExternStaticDecl(span, name_token.lexeme, static_type)
    
    # ========================================================================
    # Type Parsing
    # ========================================================================
    
    def parse_type(self):
        """Parse type expression."""
        start_token = self.current()
        
        # Volatile type: volatile T
        if self.match(TokenType.IDENTIFIER) and self.current().lexeme == "volatile":
            self.advance()
            base_type = self.parse_type()
            span = self.make_span(start_token, self.tokens[self.pos - 1])
            return VolatileType(span, base_type)
        
        # Pointer type
        if self.match(TokenType.STAR):
            self.advance()
            base_type = self.parse_type()
            span = self.make_span(start_token, self.tokens[self.pos - 1])
            return PointerType(span, base_type)
        
        # Array type
        if self.match(TokenType.LBRACKET):
            self.advance()
            elem_type = self.parse_type()
            self.expect(TokenType.SEMICOLON, "array size")
            size_expr = self.parse_expression()
            self.expect(TokenType.RBRACKET, "array type")
            span = self.make_span(start_token, self.tokens[self.pos - 1])
            return ArrayType(span, elem_type, size_expr)
        
        # Named type
        if self.match(TokenType.IDENTIFIER):
            name_token = self.current()
            self.advance()
            span = self.make_span(name_token)
            return TypeName(span, name_token.lexeme)
        
        # void type
        if self.match(TokenType.VOID):
            void_token = self.current()
            self.advance()
            span = self.make_span(void_token)
            return TypeName(span, "void")
        
        self.diag.error(
            'ERR_PARSE_EXPECTED_TOKEN',
            "expected type",
            self.current().line, self.current().column, 1,
            self.filename
        )
        return TypeName(self.make_span(start_token), "<error>")
    
    # ========================================================================
    # Statement Parsing
    # ========================================================================
    
    def parse_statement(self):
        """Parse a statement."""
        # Return statement
        if self.match(TokenType.RETURN):
            return self.parse_return()
        
        # If statement
        if self.match(TokenType.IF):
            return self.parse_if()
        
        # For loop
        if self.match(TokenType.FOR):
            return self.parse_for()
        
        # While loop
        if self.match(TokenType.WHILE):
            return self.parse_removed_while()
        
        # Break
        if self.match(TokenType.BREAK):
            start_token = self.current()
            self.advance()
            self.expect(TokenType.SEMICOLON, "break statement")
            return BreakStmt(self.make_span(start_token))
        
        # Continue
        if self.match(TokenType.CONTINUE):
            start_token = self.current()
            self.advance()
            self.expect(TokenType.SEMICOLON, "continue statement")
            return ContinueStmt(self.make_span(start_token))
        
        # Block
        if self.match(TokenType.LBRACE):
            return self.parse_block()
        
        # Let declaration (local)
        if self.match(TokenType.LET):
            return self.parse_let()
        
        # Expression statement
        start_token = self.current()
        expr = self.parse_expression()
        if expr:
            self.expect(TokenType.SEMICOLON, "expression statement")
            span = self.make_span(start_token, self.tokens[self.pos - 1])
            return ExprStmt(span, expr)
        
        return None
    
    def parse_block(self):
        """Parse block { ... }."""
        start_token = self.current()
        self.expect(TokenType.LBRACE, "block")
        
        statements = []
        while not self.match(TokenType.RBRACE) and not self.at_eof():
            stmt = self.parse_statement()
            if stmt:
                statements.append(stmt)
            else:
                # Try to recover
                self.synchronize()
                if self.match(TokenType.RBRACE):
                    break
        
        self.expect(TokenType.RBRACE, "block")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return Block(span, statements)
    
    def parse_return(self):
        """Parse return statement."""
        start_token = self.current()
        self.expect(TokenType.RETURN, "return statement")
        
        # Optional return value
        value = None
        if not self.match(TokenType.SEMICOLON):
            value = self.parse_expression()
        
        self.expect(TokenType.SEMICOLON, "return statement")
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return ReturnStmt(span, value)
    
    def parse_if(self):
        """Parse if statement with elif and else."""
        start_token = self.current()
        self.expect(TokenType.IF, "if statement")
        
        condition = self.parse_expression()
        then_block = self.parse_block()
        
        # Elif branches
        elif_branches = []
        while self.match(TokenType.ELIF):
            elif_start = self.current()
            self.advance()
            elif_cond = self.parse_expression()
            elif_block = self.parse_block()
            elif_span = self.make_span(elif_start, self.tokens[self.pos - 1])
            elif_branches.append(ElifBranch(elif_span, elif_cond, elif_block))
        
        # Else branch
        else_block = None
        if self.match(TokenType.ELSE):
            self.advance()
            else_block = self.parse_block()
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return IfStmt(span, condition, then_block, elif_branches, else_block)
    
    def parse_for(self):
        """Parse for loop."""
        start_token = self.current()
        self.expect(TokenType.FOR, "for loop")
        
        iter_token = self.expect(TokenType.IDENTIFIER, "loop iterator")
        if not iter_token:
            self.synchronize()
            return None
        
        # "in" keyword - lexer treats it as identifier
        in_token = self.expect(TokenType.IDENTIFIER, "for loop")
        if not in_token or in_token.lexeme != "in":
            self.diag.error(
                'ERR_PARSE_EXPECTED_TOKEN',
                "expected 'in' in for loop",
                self.current().line, self.current().column, 1,
                self.filename
            )
        
        # Range: start..end
        range_start = self.parse_expression()
        self.expect(TokenType.RANGE, "for loop range")
        range_end = self.parse_expression()
        
        body = self.parse_block()
        
        end_token = self.tokens[self.pos - 1]
        span = self.make_span(start_token, end_token)
        
        return ForStmt(span, iter_token.lexeme, range_start, range_end, body)
    
    def parse_removed_while(self):
        """Consume a removed while-loop construct and report a deterministic-language error."""
        start_token = self.current()
        self.expect(TokenType.WHILE, "while loop")

        if not self.match(TokenType.LBRACE) and not self.at_eof():
            self.parse_expression()

        end_token = start_token
        if self.match(TokenType.LBRACE):
            body = self.parse_block()
            end_token = self.tokens[self.pos - 1]
        else:
            self.synchronize()
            if self.pos > 0:
                end_token = self.tokens[self.pos - 1]

        self.diag.error(
            'E_WHILE_REMOVED',
            "while loops are not part of BASIS; use a bounded for loop or recursion with @recursion(max=N)",
            start_token.line, start_token.column, start_token.length,
            self.filename
        )

        span = self.make_span(start_token, end_token)
        return Block(span, [])
    
    # ========================================================================
    # Expression Parsing (Precedence Climbing)
    # ========================================================================
    
    def parse_expression(self):
        """Parse expression (entry point)."""
        return self.parse_assignment()
    
    def parse_assignment(self):
        """Parse assignment (lowest precedence)."""
        expr = self.parse_logical_or()
        
        # Check for assignment operators
        if self.match(TokenType.EQ, TokenType.PLUS_EQ, TokenType.MINUS_EQ,
                     TokenType.STAR_EQ, TokenType.SLASH_EQ, TokenType.PERCENT_EQ,
                     TokenType.AMP_EQ, TokenType.PIPE_EQ, TokenType.CARET_EQ,
                     TokenType.LT_LT_EQ, TokenType.GT_GT_EQ):
            op_token = self.current()
            self.advance()
            value = self.parse_assignment()
            end_token = self.tokens[self.pos - 1]
            span = SourceSpan(expr.span.start_line, expr.span.start_col,
                            end_token.line, end_token.column + end_token.length)
            return AssignmentExpr(span, expr, op_token.lexeme, value)
        
        return expr
    
    def parse_logical_or(self):
        """Parse logical OR (||)."""
        left = self.parse_logical_and()
        
        while self.match(TokenType.PIPE_PIPE):
            op_token = self.current()
            self.advance()
            right = self.parse_logical_and()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_logical_and(self):
        """Parse logical AND (&&)."""
        left = self.parse_equality()
        
        while self.match(TokenType.AMP_AMP):
            op_token = self.current()
            self.advance()
            right = self.parse_equality()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_equality(self):
        """Parse equality (==, !=)."""
        left = self.parse_comparison()
        
        while self.match(TokenType.EQ_EQ, TokenType.NE):
            op_token = self.current()
            self.advance()
            right = self.parse_comparison()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_comparison(self):
        """Parse comparison (<, >, <=, >=)."""
        left = self.parse_bitwise_or()
        
        while self.match(TokenType.LT, TokenType.GT, TokenType.LE, TokenType.GE):
            op_token = self.current()
            self.advance()
            right = self.parse_bitwise_or()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_bitwise_or(self):
        """Parse bitwise OR (|)."""
        left = self.parse_bitwise_xor()
        
        while self.match(TokenType.PIPE) and not self.peek().type == TokenType.PIPE:
            op_token = self.current()
            self.advance()
            right = self.parse_bitwise_xor()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_bitwise_xor(self):
        """Parse bitwise XOR (^)."""
        left = self.parse_bitwise_and()
        
        while self.match(TokenType.CARET):
            op_token = self.current()
            self.advance()
            right = self.parse_bitwise_and()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_bitwise_and(self):
        """Parse bitwise AND (&)."""
        left = self.parse_shift()
        
        while self.match(TokenType.AMP) and not self.peek().type == TokenType.AMP:
            op_token = self.current()
            self.advance()
            right = self.parse_shift()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_shift(self):
        """Parse shift (<<, >>)."""
        left = self.parse_additive()
        
        while self.match(TokenType.LT_LT, TokenType.GT_GT):
            op_token = self.current()
            self.advance()
            right = self.parse_additive()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_additive(self):
        """Parse addition and subtraction (+, -)."""
        left = self.parse_multiplicative()
        
        while self.match(TokenType.PLUS, TokenType.MINUS):
            op_token = self.current()
            self.advance()
            right = self.parse_multiplicative()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_multiplicative(self):
        """Parse multiplication, division, modulo (*, /, %)."""
        left = self.parse_unary()
        
        while self.match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op_token = self.current()
            self.advance()
            right = self.parse_unary()
            span = SourceSpan(left.span.start_line, left.span.start_col,
                            right.span.end_line, right.span.end_col)
            left = BinaryExpr(span, left, op_token.lexeme, right)
        
        return left
    
    def parse_unary(self):
        """Parse unary operators (!, -, ~, &, *)."""
        if self.match(TokenType.BANG, TokenType.MINUS, TokenType.TILDE):
            op_token = self.current()
            self.advance()
            operand = self.parse_unary()
            span = self.make_span(op_token, self.tokens[self.pos - 1])
            return UnaryExpr(span, op_token.lexeme, operand)
        
        # Address-of
        if self.match(TokenType.AMP):
            op_token = self.current()
            self.advance()
            operand = self.parse_unary()
            span = self.make_span(op_token, self.tokens[self.pos - 1])
            return AddressOfExpr(span, operand)
        
        # Dereference
        if self.match(TokenType.STAR):
            op_token = self.current()
            self.advance()
            operand = self.parse_unary()
            span = self.make_span(op_token, self.tokens[self.pos - 1])
            return DereferenceExpr(span, operand)
        
        return self.parse_postfix()
    
    def parse_postfix(self):
        """Parse postfix expressions (call, index, field access)."""
        expr = self.parse_primary()
        
        while True:
            # Function call
            if self.match(TokenType.LPAREN):
                self.advance()
                args = []
                
                while not self.match(TokenType.RPAREN) and not self.at_eof():
                    args.append(self.parse_expression())
                    
                    if not self.match(TokenType.RPAREN):
                        if not self.consume(TokenType.COMMA):
                            break
                
                self.expect(TokenType.RPAREN, "function call")
                end_token = self.tokens[self.pos - 1]
                span = SourceSpan(expr.span.start_line, expr.span.start_col,
                                end_token.line, end_token.column + end_token.length)
                expr = CallExpr(span, expr, args)
            
            # Array indexing
            elif self.match(TokenType.LBRACKET):
                self.advance()
                index = self.parse_expression()
                self.expect(TokenType.RBRACKET, "array index")
                end_token = self.tokens[self.pos - 1]
                span = SourceSpan(expr.span.start_line, expr.span.start_col,
                                end_token.line, end_token.column + end_token.length)
                expr = IndexExpr(span, expr, index)
            
            # Field access
            elif self.match(TokenType.DOT):
                self.advance()
                field_token = self.expect(TokenType.IDENTIFIER, "field name")
                if not field_token:
                    break
                span = SourceSpan(expr.span.start_line, expr.span.start_col,
                                field_token.line, field_token.column + field_token.length)
                expr = FieldAccessExpr(span, expr, field_token.lexeme)
            
            # Module-qualified name (::)
            elif self.match(TokenType.COLON):
                # Check if next token is also COLON
                if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].type == TokenType.COLON:
                    self.advance()  # consume first :
                    self.advance()  # consume second :
                    member_token = self.expect(TokenType.IDENTIFIER, "module member name")
                    if not member_token:
                        break
                    span = SourceSpan(expr.span.start_line, expr.span.start_col,
                                    member_token.line, member_token.column + member_token.length)
                    # For now, represent as FieldAccessExpr - semantic analyzer will handle module resolution
                    expr = FieldAccessExpr(span, expr, member_token.lexeme)
                else:
                    break

            # Cast expression: expr as Type
            elif self.match(TokenType.AS):
                self.advance()
                target_type = self.parse_type()
                end_token = self.tokens[self.pos - 1]
                span = SourceSpan(expr.span.start_line, expr.span.start_col,
                                 end_token.line, end_token.column + end_token.length)
                expr = CastExpr(span, expr, target_type)
            
            else:
                break
        
        return expr
    
    def parse_primary(self):
        """Parse primary expressions (literals, identifiers, parenthesized)."""
        start_token = self.current()
        
        # Integer literal
        if self.match(TokenType.INTEGER):
            token = self.current()
            self.advance()
            span = self.make_span(token)
            return LiteralExpr(span, token.lexeme, 'int')
        
        # Float literal
        if self.match(TokenType.FLOAT):
            token = self.current()
            self.advance()
            span = self.make_span(token)
            return LiteralExpr(span, token.lexeme, 'float')
        
        # String literal
        if self.match(TokenType.STRING):
            token = self.current()
            self.advance()
            span = self.make_span(token)
            return LiteralExpr(span, token.lexeme, 'string')
        
        # Boolean literals
        if self.match(TokenType.TRUE, TokenType.FALSE):
            token = self.current()
            self.advance()
            span = self.make_span(token)
            return LiteralExpr(span, token.lexeme, 'bool')
        
        # Array literal: [expr, expr, ...]
        if self.match(TokenType.LBRACKET):
            return self.parse_array_literal()
        
        # Identifier (could be simple identifier or struct literal)
        if self.match(TokenType.IDENTIFIER):
            token = self.current()
            self.advance()
            
            # Check for struct literal: StructName { ... }
            # Only treat as struct literal if identifier starts with uppercase (naming convention)
            if self.match(TokenType.LBRACE) and token.lexeme and token.lexeme[0].isupper():
                return self.parse_struct_literal(token)
            
            # Just an identifier
            span = self.make_span(token)
            return IdentifierExpr(span, token.lexeme)
        
        # Parenthesized expression
        if self.match(TokenType.LPAREN):
            self.advance()
            expr = self.parse_expression()
            self.expect(TokenType.RPAREN, "parenthesized expression")
            return expr
        
        # Error
        token = self.current()
        self.diag.error(
            'ERR_PARSE_EXPECTED_TOKEN',
            f"expected expression, found {self.current().type.name}",
            self.current().line, self.current().column, 1,
            self.filename
        )
        
        # Advance to prevent infinite loop
        self.advance()
        
        # Return error node
        return IdentifierExpr(self.make_span(token), "<error>")
    
    def parse_array_literal(self):
        """Parse array literal: [expr1, expr2, ...] or [value; count] or [value; count; idx: val, ...]."""
        start_token = self.current()
        self.expect(TokenType.LBRACKET, "array literal")
        
        # Empty array
        if self.match(TokenType.RBRACKET):
            self.advance()
            span = self.make_span(start_token, self.previous())
            return ArrayLiteralExpr(span, [])
        
        # Parse first expression
        first_expr = self.parse_expression()
        
        # Check for repeat syntax: [value; count] or [value; count; overrides...]
        if self.match(TokenType.SEMICOLON):
            self.advance()
            count_expr = self.parse_expression()
            
            # Check for sparse overrides: [value; count; idx: val, ...]
            overrides: list = []
            if self.match(TokenType.SEMICOLON):
                self.advance()
                while True:
                    # Parse index: value
                    idx_expr = self.parse_expression()
                    self.expect(TokenType.COLON, "array override (index: value)")
                    val_expr = self.parse_expression()
                    overrides.append(ArrayOverride(self.make_span(start_token), idx_expr, val_expr))
                    
                    if not self.match(TokenType.COMMA):
                        break
                    self.advance()
                    
                    # Check for trailing comma
                    if self.match(TokenType.RBRACKET):
                        break
            
            end_token = self.current()
            self.expect(TokenType.RBRACKET, "array repeat literal")
            span = self.make_span(start_token, end_token)
            return ArrayRepeatExpr(span, first_expr, count_expr, overrides)
        
        # Regular list syntax: [expr1, expr2, ...]
        elements: list = [first_expr]
        
        while self.match(TokenType.COMMA):
            self.advance()
            
            # Allow trailing comma
            if self.match(TokenType.RBRACKET):
                break
            
            elements.append(self.parse_expression())
        
        end_token = self.current()
        self.expect(TokenType.RBRACKET, "array literal")
        
        span = self.make_span(start_token, end_token)
        return ArrayLiteralExpr(span, elements)
    
    def parse_struct_literal(self, struct_name_token):
        """Parse struct literal: StructName { field: value, ... }."""
        start_token = struct_name_token
        struct_name = struct_name_token.lexeme
        
        self.expect(TokenType.LBRACE, "struct literal")
        
        field_inits = []
        
        # Empty struct literal
        if self.match(TokenType.RBRACE):
            end_token = self.current()
            self.advance()
            span = self.make_span(start_token, end_token)
            return StructLiteralExpr(span, struct_name, field_inits)
        
        # Parse field initializers
        while True:
            field_token = self.current()
            field_name_token = self.expect(TokenType.IDENTIFIER, "field name in struct literal")
            if not field_name_token:
                break
            field_name = field_name_token.lexeme
            
            self.expect(TokenType.COLON, "struct field initializer")
            
            value = self.parse_expression()
            
            field_span = self.make_span(field_token)
            field_init = FieldInit(field_span, field_name, value)
            field_inits.append(field_init)
            
            if not self.match(TokenType.COMMA):
                break
            self.advance()
            
            # Allow trailing comma
            if self.match(TokenType.RBRACE):
                break
        
        end_token = self.current()
        self.expect(TokenType.RBRACE, "struct literal")
        
        span = self.make_span(start_token, end_token)
        return StructLiteralExpr(span, struct_name, field_inits)


def test_parser():
    """Test parser with simple program."""
    from lexer import Lexer
    
    source = """
    fn add(x: i32, y: i32) -> i32 {
        return x + y;
    }
    
    fn main() -> i32 {
        let result: i32 = add(10, 20);
        return result;
    }
    """
    
    print("Parsing test program...")
    print("=" * 70)
    
    diag = DiagnosticEngine()
    lexer = Lexer(source, diag_engine=diag)
    tokens = lexer.tokenize()
    
    if diag.has_errors():
        print("Lexer errors:")
        diag.print_all()
        return
    
    parser = Parser(tokens, diag_engine=diag)
    module = parser.parse("test")
    
    if diag.has_errors():
        print("Parser errors:")
        diag.print_all()
    else:
        print("Parse successful!")
        print("\nAST:")
        print_ast(module)


if __name__ == '__main__':
    test_parser()

