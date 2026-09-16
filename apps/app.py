from flask import Flask


def create_app(config_name: str = "local"):
    app = Flask(__name__)

    @app.route("/")
    def hello_world():
        return "Hello"

    return app


app = create_app()
