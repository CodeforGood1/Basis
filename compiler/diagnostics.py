"""
BASIS Compiler Diagnostics System
Minimal error reporting for lexer and future compiler stages.
"""

class Diagnostic:
    """Represents a single diagnostic message (error, warning, note)."""
    
    def __init__(self, severity, err_code, message, line, column, length=1, filename="<input>"):
        self.severity = severity  # 'error', 'warning', 'note'
        self.err_code = err_code
        self.message = message
        self.line = line
        self.column = column
        self.length = length
        self.filename = filename
    
    def __str__(self):
        return f"{self.filename}:{self.line}:{self.column}: {self.severity}: {self.message} [{self.err_code}]"


class DiagnosticEngine:
    """Collects and reports diagnostics."""
    
    def __init__(self):
        self.diagnostics = []
        self.error_count = 0
        self.warning_count = 0
    
    def report(self, severity, err_code, message, line, column, length=1, filename="<input>"):
        """Report a diagnostic."""
        diag = Diagnostic(severity, err_code, message, line, column, length, filename)
        self.diagnostics.append(diag)
        
        if severity == 'error':
            self.error_count += 1
        elif severity == 'warning':
            self.warning_count += 1
        
        return diag
    
    def error(self, err_code, message, line, column, length=1, filename="<input>"):
        """Report an error."""
        return self.report('error', err_code, message, line, column, length, filename)
    
    def warning(self, err_code, message, line, column, length=1, filename="<input>"):
        """Report a warning."""
        return self.report('warning', err_code, message, line, column, length, filename)
    
    def has_errors(self):
        """Check if any errors were reported."""
        return self.error_count > 0
    
    def print_all(self):
        """Print all diagnostics to stdout."""
        for diag in self.diagnostics:
            print(diag)
    
    def clear(self):
        """Clear all diagnostics."""
        self.diagnostics.clear()
        self.error_count = 0
        self.warning_count = 0
