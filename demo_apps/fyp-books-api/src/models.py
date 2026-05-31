from sqlalchemy import Column, Integer, String
from database import Base


class Book(Base):
    """ 
    Book model create a table books in the database:
    - `id` (integer): Unique identifier for the book.
    - `title` (string): Title of the book.
    - `author` (string): Author of the book.
    - `year` (integer): Year of publication.
    - `isbn` (string): ISBN (International Standard Book Number) of the book.
    """
    __tablename__ = 'books'

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100),nullable=False)
    author = Column(String(100),nullable=False)
    year = Column(Integer,nullable=False)
    isbn = Column(String(50),nullable=False)

