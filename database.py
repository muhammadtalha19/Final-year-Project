from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def init_database(app):
    db.init_app(app)
    if app.config.get("AUTO_CREATE_DB") or app.config.get("TESTING"):
        with app.app_context():
            db.create_all()
