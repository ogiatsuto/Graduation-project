from flask import Flask, render_template


def create_app(config_name: str = "local"):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    @app.route("/")
    def interview_practice():
        return render_template("index.html")

    return app


app = create_app()

