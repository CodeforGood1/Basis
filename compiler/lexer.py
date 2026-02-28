"""
BASIS Lexer - Tokenization for BASIS source files
Converts source text into a stream of tokens with location tracking.
"""

from enum import Enum, auto
from diagnostics import DiagnosticEngine


class TokenType(Enum):
    """All token types in BASIS."""
    # Special
    EOF = auto()
    
    # Identifiers and literals
    IDENTIFIER = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    
    # Keywords
    FN = auto()
    PUBLIC = auto()
    PRIVATE = auto()
    IMPORT = auto()
    AS = auto()
    EXTERN = auto()
    RETURN = auto()
    LET = auto()
    CONST = auto()
    STRUCT = auto()
    IF = auto()
    ELSE = auto()
    ELIF = auto()
    FOR = auto()
    BREAK = auto()
    CONTINUE = auto()
    WHILE = auto()
    ALLOC = auto()
    FREE = auto()
    EXIT = auto()
    TRUE = auto()
    FALSE = auto()
    VOID = auto()
    STATIC = auto()
    
    # Symbols
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    LBRACKET = auto()    # [
    RBRACKET = auto()    # ]
    SEMICOLON = auto()   # ;
    COMMA = auto()       # ,
    DOT = auto()         # .
    COLON = auto()       # :
    ARROW = auto()       # ->
    RANGE = auto()       # ..
    HASH = auto()        # #
    TILDE = auto()        # ~
    AT = auto()           # @
    
    # Operators
    EQ = auto()          # =
    PLUS = auto()        # +
    MINUS = auto()       # -
    STAR = auto()        # *
    SLASH = auto()       # /
    PERCENT = auto()     # %
    AMP = auto()         # &
    PIPE = auto()        # |
    CARET = auto()       # ^
    BANG = auto()        # !
    LT = auto()          # <
    GT = auto()          # >
    LE = auto()          # <=
    GE = auto()          # >=
    EQ_EQ = auto()       # ==
    NE = auto()          # !=
    AMP_AMP = auto()     # &&
    PIPE_PIPE = auto()   # ||
    PLUS_EQ = auto()     # +=
    MINUS_EQ = auto()    # -=
    STAR_EQ = auto()     # *=
    SLASH_EQ = auto()    # /=
    PERCENT_EQ = auto()  # %=
    AMP_EQ = auto()      # &=
    PIPE_EQ = auto()     # |=
    CARET_EQ = auto()    # ^=
    LT_LT = auto()       # <<
    GT_GT = auto()       # >>
    LT_LT_EQ = auto()    # <<=
    GT_GT_EQ = auto()    # >>=


class Token:
    """Represents a single token with location information."""
    
    def __init__(self, token_type, lexeme, line, column, length=None):
        self.type = token_type
        self.lexeme = lexeme
        self.line = line
        self.column = column
        self.length = length if length is not None else len(lexeme)
    
    def __repr__(self):
        return f"Token({self.type.name}, '{self.lexeme}', {self.line}:{self.column})"


# Keywords mapping
KEYWORDS = {
    'fn': TokenType.FN,
    'public': TokenType.PUBLIC,
    'private': TokenType.PRIVATE,
    'import': TokenType.IMPORT,
    'as': TokenType.AS,
    'extern': TokenType.EXTERN,
    'return': TokenType.RETURN,
    'let': TokenType.LET,
    'const': TokenType.CONST,
    'struct': TokenType.STRUCT,
    'if': TokenType.IF,
    'else': TokenType.ELSE,
    'elif': TokenType.ELIF,
    'for': TokenType.FOR,
    'while': TokenType.WHILE,
    'break': TokenType.BREAK,
    'continue': TokenType.CONTINUE,
    'true': TokenType.TRUE,
    'false': TokenType.FALSE,
    'void': TokenType.VOID,
    'static': TokenType.STATIC,
}


class Lexer:
    """Tokenizer for BASIS source code."""
    
    def __init__(self, source, filename="<input>", diag_engine=None):
        self.source = source
        self.filename = filename
        self.diag = diag_engine or DiagnosticEngine()
        
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens = []
    
    def current_char(self):
        """Get current character without advancing."""
        if self.pos >= len(self.source):
            return None
        return self.source[self.pos]
    
    def peek_char(self, offset=1):
        """Look ahead at character."""
        pos = self.pos + offset
        if pos >= len(self.source):
            return None
        return self.source[pos]
    
    def advance(self):
        """Move to next character and update position."""
        if self.pos < len(self.source):
            if self.source[self.pos] == '\n':
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            self.pos += 1
    
    def skip_whitespace(self):
        """Skip whitespace characters."""
        ch = self.current_char()
        while ch and ch in ' \t\n\r':
            self.advance()
            ch = self.current_char()
    
    def skip_line_comment(self):
        """Skip // comment to end of line."""
        while self.current_char() and self.current_char() != '\n':
            self.advance()
    
    def skip_block_comment(self):
        """Skip /* */ block comment with nesting support."""
        start_line = self.line
        start_col = self.column
        
        self.advance()  # skip '/'
        self.advance()  # skip '*'
        
        depth = 1
        while depth > 0 and self.current_char():
            if self.current_char() == '/' and self.peek_char() == '*':
                self.advance()
                self.advance()
                depth += 1
            elif self.current_char() == '*' and self.peek_char() == '/':
                self.advance()
                self.advance()
                depth -= 1
            else:
                self.advance()
        
        if depth > 0:
            self.diag.error('ERR_LEX_UNTERM_BLOCK', 
                          "unterminated block comment",
                          start_line, start_col, 2)
    
    def lex_string(self):
        """Lex a string literal with C-style escapes."""
        start_line = self.line
        start_col = self.column
        
        self.advance()  # skip opening "
        chars = []
        
        while self.current_char() and self.current_char() != '"':
            if self.current_char() == '\\':
                self.advance()
                escape_char = self.current_char()
                
                if escape_char is None:
                    break
                
                # Handle escape sequences
                escape_map = {
                    'n': '\n',
                    't': '\t',
                    'r': '\r',
                    '\\': '\\',
                    '"': '"',
                    '0': '\0',
                }
                
                if escape_char in escape_map:
                    chars.append(escape_map[escape_char])
                    self.advance()
                elif escape_char == 'x':
                    # \xHH hex escape
                    self.advance()
                    hex_chars = []
                    for _ in range(2):
                        ch = self.current_char()
                        if ch and ch in '0123456789abcdefABCDEF':
                            hex_chars.append(ch)
                            self.advance()
                        else:
                            break
                    if len(hex_chars) == 2:
                        chars.append(chr(int(''.join(hex_chars), 16)))
                    else:
                        self.diag.error('ERR_LEX_BAD_ESCAPE',
                                      "invalid hex escape sequence",
                                      self.line, self.column - 1, 1)
                elif escape_char == 'u':
                    # \u{...} unicode escape
                    self.advance()
                    if self.current_char() == '{':
                        self.advance()
                        hex_chars = []
                        ch = self.current_char()
                        while ch and ch != '}':
                            if ch in '0123456789abcdefABCDEF':
                                hex_chars.append(ch)
                                self.advance()
                                ch = self.current_char()
                            else:
                                break
                        if self.current_char() == '}':
                            self.advance()
                            if hex_chars:
                                try:
                                    chars.append(chr(int(''.join(hex_chars), 16)))
                                except ValueError:
                                    self.diag.error('ERR_LEX_BAD_ESCAPE',
                                                  "invalid unicode escape",
                                                  self.line, self.column, 1)
                        else:
                            self.diag.error('ERR_LEX_BAD_ESCAPE',
                                          "unterminated unicode escape",
                                          self.line, self.column, 1)
                    else:
                        self.diag.error('ERR_LEX_BAD_ESCAPE',
                                      "expected '{' after \\u",
                                      self.line, self.column, 1)
                else:
                    self.diag.error('ERR_LEX_BAD_ESCAPE',
                                  f"unknown escape sequence '\\{escape_char}'",
                                  self.line, self.column - 1, 2)
                    chars.append(escape_char)
                    self.advance()
            elif self.current_char() == '\n':
                self.diag.error('ERR_LEX_UNTERM_STRING',
                              "unterminated string literal (newline)",
                              start_line, start_col, 1)
                break
            else:
                chars.append(self.current_char())
                self.advance()
        
        if self.current_char() == '"':
            self.advance()
            string_value = ''.join(chars)
            return Token(TokenType.STRING, string_value, start_line, start_col, 
                        self.column - start_col)
        else:
            self.diag.error('ERR_LEX_UNTERM_STRING',
                          "unterminated string literal",
                          start_line, start_col, 1)
            return Token(TokenType.STRING, ''.join(chars), start_line, start_col)
    
    def lex_number(self):
        """Lex integer or float literal."""
        start_line = self.line
        start_col = self.column
        
        # Check for hex (0x) or binary (0b)
        peek = self.peek_char()
        if self.current_char() == '0' and peek and peek in 'xXbB':
            base_char = peek.lower()
            self.advance()  # skip '0'
            self.advance()  # skip 'x' or 'b'
            
            digits = []
            if base_char == 'x':
                ch = self.current_char()
                while ch and ch in '0123456789abcdefABCDEF_':
                    if ch != '_':
                        digits.append(ch)
                    self.advance()
                    ch = self.current_char()
            else:  # binary
                ch = self.current_char()
                while ch and ch in '01_':
                    if ch != '_':
                        digits.append(ch)
                    self.advance()
                    ch = self.current_char()
            
            if not digits:
                self.diag.error('ERR_LEX_BAD_NUMBER',
                              f"expected digits after 0{base_char}",
                              start_line, start_col, 2)
                return Token(TokenType.INTEGER, "0", start_line, start_col)
            
            lexeme = ('0x' if base_char == 'x' else '0b') + ''.join(digits)
            return Token(TokenType.INTEGER, lexeme, start_line, start_col,
                        self.column - start_col)
        
        # Decimal number (int or float)
        digits = []
        ch = self.current_char()
        while ch and (ch.isdigit() or ch == '_'):
            if ch != '_':
                digits.append(ch)
            self.advance()
            ch = self.current_char()
        
        # Check for decimal point
        peek = self.peek_char()
        if self.current_char() == '.' and peek and peek.isdigit():
            digits.append('.')
            self.advance()
            
            ch = self.current_char()
            while ch and (ch.isdigit() or ch == '_'):
                if ch != '_':
                    digits.append(ch)
                self.advance()
                ch = self.current_char()
            
            # Check for exponent
            ch = self.current_char()
            if ch and ch in 'eE':
                digits.append(ch)
                self.advance()
                
                ch = self.current_char()
                if ch and ch in '+-':
                    digits.append(ch)
                    self.advance()
                
                exp_start = len(digits)
                ch = self.current_char()
                while ch and (ch.isdigit() or ch == '_'):
                    if ch != '_':
                        digits.append(ch)
                    self.advance()
                    ch = self.current_char()
                
                if len(digits) == exp_start:
                    self.diag.error('ERR_LEX_BAD_NUMBER',
                                  "expected digits after exponent",
                                  start_line, start_col, 1)
            
            return Token(TokenType.FLOAT, ''.join(digits), start_line, start_col,
                        self.column - start_col)
        
        # Check for exponent on integer
        ch = self.current_char()
        if ch and ch in 'eE':
            digits.append(ch)
            self.advance()
            
            ch = self.current_char()
            if ch and ch in '+-':
                digits.append(ch)
                self.advance()
            
            exp_start = len(digits)
            ch = self.current_char()
            while ch and (ch.isdigit() or ch == '_'):
                if ch != '_':
                    digits.append(ch)
                self.advance()
                ch = self.current_char()
            
            if len(digits) == exp_start:
                self.diag.error('ERR_LEX_BAD_NUMBER',
                              "expected digits after exponent",
                              start_line, start_col, 1)
            
            return Token(TokenType.FLOAT, ''.join(digits), start_line, start_col,
                        self.column - start_col)
        
        return Token(TokenType.INTEGER, ''.join(digits), start_line, start_col,
                    self.column - start_col)
    
    def lex_identifier(self):
        """Lex identifier or keyword."""
        start_line = self.line
        start_col = self.column
        
        chars = []
        ch = self.current_char()
        while ch and (ch.isalnum() or ch == '_'):
            # Enforce ASCII-only identifiers
            if ord(ch) > 127:
                self.diag.error('ERR_LEX_INVALID_CHAR',
                              f"non-ASCII character in identifier: U+{ord(ch):04X}",
                              self.line, self.column, 1)
                self.advance()
                ch = self.current_char()
                continue
            
            chars.append(ch)
            self.advance()
            ch = self.current_char()
        
        lexeme = ''.join(chars)
        
        # Check if it's a keyword
        token_type = KEYWORDS.get(lexeme, TokenType.IDENTIFIER)
        
        return Token(token_type, lexeme, start_line, start_col, self.column - start_col)
    
    def lex_token(self):
        """Lex a single token."""
        self.skip_whitespace()
        
        if not self.current_char():
            return Token(TokenType.EOF, '', self.line, self.column, 0)
        
        start_line = self.line
        start_col = self.column
        ch = self.current_char()
        
        # Comments
        if ch == '/' and self.peek_char() == '/':
            self.skip_line_comment()
            return self.lex_token()  # Continue to next token
        
        if ch == '/' and self.peek_char() == '*':
            self.skip_block_comment()
            return self.lex_token()  # Continue to next token
        
        # String literals
        if ch == '"':
            return self.lex_string()
        
        # Numbers
        if ch and ch.isdigit():
            return self.lex_number()
        
        # Identifiers and keywords
        if ch and (ch.isalpha() or ch == '_'):
            return self.lex_identifier()
        
        # Multi-character operators
        if ch == '-' and self.peek_char() == '>':
            self.advance()
            self.advance()
            return Token(TokenType.ARROW, '->', start_line, start_col, 2)
        
        if ch == '.' and self.peek_char() == '.':
            self.advance()
            self.advance()
            return Token(TokenType.RANGE, '..', start_line, start_col, 2)
        
        if ch == '=' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.EQ_EQ, '==', start_line, start_col, 2)
        
        if ch == '!' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.NE, '!=', start_line, start_col, 2)
        
        if ch == '<' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.LE, '<=', start_line, start_col, 2)
        
        if ch == '>' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.GE, '>=', start_line, start_col, 2)
        
        if ch == '&' and self.peek_char() == '&':
            self.advance()
            self.advance()
            return Token(TokenType.AMP_AMP, '&&', start_line, start_col, 2)
        
        if ch == '|' and self.peek_char() == '|':
            self.advance()
            self.advance()
            return Token(TokenType.PIPE_PIPE, '||', start_line, start_col, 2)
        
        if ch == '+' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.PLUS_EQ, '+=', start_line, start_col, 2)
        
        if ch == '-' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.MINUS_EQ, '-=', start_line, start_col, 2)
        
        if ch == '*' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.STAR_EQ, '*=', start_line, start_col, 2)
        
        if ch == '/' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.SLASH_EQ, '/=', start_line, start_col, 2)
        
        if ch == '%' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.PERCENT_EQ, '%=', start_line, start_col, 2)
        
        if ch == '&' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.AMP_EQ, '&=', start_line, start_col, 2)
        
        if ch == '|' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.PIPE_EQ, '|=', start_line, start_col, 2)
        
        if ch == '^' and self.peek_char() == '=':
            self.advance()
            self.advance()
            return Token(TokenType.CARET_EQ, '^=', start_line, start_col, 2)
        
        if ch == '<' and self.peek_char() == '<':
            self.advance()
            self.advance()
            if self.current_char() == '=':
                self.advance()
                return Token(TokenType.LT_LT_EQ, '<<=', start_line, start_col, 3)
            return Token(TokenType.LT_LT, '<<', start_line, start_col, 2)
        
        if ch == '>' and self.peek_char() == '>':
            self.advance()
            self.advance()
            if self.current_char() == '=':
                self.advance()
                return Token(TokenType.GT_GT_EQ, '>>=', start_line, start_col, 3)
            return Token(TokenType.GT_GT, '>>', start_line, start_col, 2)
        
        # Single-character tokens
        single_char_tokens = {
            '(': TokenType.LPAREN,
            ')': TokenType.RPAREN,
            '{': TokenType.LBRACE,
            '}': TokenType.RBRACE,
            '[': TokenType.LBRACKET,
            ']': TokenType.RBRACKET,
            ';': TokenType.SEMICOLON,
            ',': TokenType.COMMA,
            '.': TokenType.DOT,
            ':': TokenType.COLON,
            '=': TokenType.EQ,
            '+': TokenType.PLUS,
            '-': TokenType.MINUS,
            '*': TokenType.STAR,
            '/': TokenType.SLASH,
            '%': TokenType.PERCENT,
            '&': TokenType.AMP,
            '|': TokenType.PIPE,
            '^': TokenType.CARET,
            '!': TokenType.BANG,
            '<': TokenType.LT,
            '>': TokenType.GT,
            '#': TokenType.HASH,
            '~': TokenType.TILDE,
            '@': TokenType.AT,
        }
        
        if ch in single_char_tokens:
            self.advance()
            return Token(single_char_tokens[ch], ch, start_line, start_col, 1)
        
        # Invalid character
        self.diag.error('ERR_LEX_INVALID_CHAR',
                      f"invalid character: '{ch}' (U+{ord(ch):04X})" if ch else "unexpected end of file",
                      start_line, start_col, 1)
        self.advance()
        return self.lex_token()  # Continue to next token
    
    def tokenize(self):
        """Tokenize the entire source and return list of tokens."""
        self.tokens = []
        
        while True:
            token = self.lex_token()
            self.tokens.append(token)
            
            if token.type == TokenType.EOF:
                break
        
        return self.tokens


def test_lexer():
    """Simple test function for the lexer."""
    
    test_source = """
    // Test BASIS program
    fn main() -> i32 {
        let x: i32 = 42;
        let y: f32 = 3.14;
        let name: *u8 = "Hello, BASIS!";
        return 0;
    }
    
    /* Block comment
       with multiple lines */
    
    const MAX: u32 = 0xFF;
    """
    
    diag = DiagnosticEngine()
    lexer = Lexer(test_source, diag_engine=diag)
    tokens = lexer.tokenize()
    
    print("Tokens:")
    for token in tokens:
        if token.type != TokenType.EOF:
            print(f"  {token}")
    
    print(f"\nDiagnostics: {diag.error_count} errors, {diag.warning_count} warnings")
    if diag.has_errors():
        diag.print_all()


if __name__ == '__main__':
    test_lexer()
