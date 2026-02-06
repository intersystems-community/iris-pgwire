import ast


class ShadowFinder(ast.NodeVisitor):
    def __init__(self):
        self.parent_stack = []
        self.targets = {"sql", "params", "session_id"}

    def visit_FunctionDef(self, node):
        self.parent_stack.append(node.name)
        # Check signature
        for arg in node.args.args:
            if arg.arg in self.targets and len(self.parent_stack) > 1:
                print(
                    f"Shadowing in signature: {' -> '.join(self.parent_stack)}: arg '{arg.arg}' at line {arg.lineno}"
                )

        self.generic_visit(node)
        self.parent_stack.pop()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store) and node.id in self.targets:
            if len(self.parent_stack) > 1:
                print(
                    f"Shadowing assignment: {' -> '.join(self.parent_stack)}: var '{node.id}' at line {node.lineno}"
                )


with open("src/iris_pgwire/iris_executor.py") as f:
    tree = ast.parse(f.read())

finder = ShadowFinder()
finder.visit(tree)
