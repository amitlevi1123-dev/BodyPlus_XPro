# debug_routes.py
from admin_web import runpod_proxy  # או main / server לפי מה שאתה מריץ בפועל
import inspect

def print_routes(app):
    print("\n== Registered Routes ==")
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        methods = ','.join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
        view_func = app.view_functions[rule.endpoint]
        source = inspect.getfile(view_func)
        print(f"[{methods}] {rule.rule}  --> {rule.endpoint}  ({source})")

if __name__ == "__main__":
    app = runpod_proxy.app  # או main.app / server.create_app() אם זה יוצר את האפליקציה
    print_routes(app)
ASD