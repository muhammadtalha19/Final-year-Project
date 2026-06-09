from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base


"""
create database connection object from sqlalchemy database connection string
note uncomment the database you are using and comment the others replace url_database with your database connection string

"""

#url_database = 'mysql+pymysql://root:mart@localhost:3306/books' #replace with your mysql database for conection to mysql
#url_database = "postgres://localhost:5432/books" #replace with your postgres database for conection to postgres
url_database = "sqlite:///database.db"



engine = create_engine(url_database)
session = sessionmaker(autoflush=False, autocommit=False, bind=engine)
Base = declarative_base()





