import ast
import sys
import os

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    lines_to_replace = []
    
    class LogVisitor(ast.NodeVisitor):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id == 'logger':
                    if node.func.attr == 'debug':
                        lines_to_replace.append((node.lineno, node.end_lineno))
                    elif node.func.attr == 'info':
                        # Check if first arg is a string starting with AST Surgery or Drag
                        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            val = node.args[0].value
                            if val.startswith('AST Surgery') or val.startswith('AST Injection') or val.startswith('Drag'):
                                lines_to_replace.append((node.lineno, node.end_lineno))
            self.generic_visit(node)

    LogVisitor().visit(tree)

    if not lines_to_replace:
        return

    lines = source.split('\n')
    for start, end in lines_to_replace:
        # Get indentation of the first line
        first_line = lines[start - 1]
        indent = first_line[:len(first_line) - len(first_line.lstrip())]
        
        for i in range(start - 1, end):
            if i == start - 1:
                lines[i] = indent + 'pass'
            else:
                lines[i] = '' # Clear the rest of the lines
                
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

for root, _, files in os.walk('engine'):
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))
