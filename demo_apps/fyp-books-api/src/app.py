from fastapi import FastAPI, HTTPException, Depends, status
from typing import Annotated
from sqlalchemy.orm import Session
from database import engine,session
from schema import bookbase
from models import *

"""
main function for create queries and routes for the api server and end point

"""


app = FastAPI()

Base.metadata.create_all(bind=engine)


def get_db_connection():
    db = session()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db_connection)]


# support for fetching all books

@app.get("/books/", status_code=status.HTTP_200_OK)
async def fetch_books(db: db_dependency):
    all_books = db.query(Book).all()
    if all_books is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No books found")

    serialized_books = []
    for book in all_books:
         serialized_book = {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "year": book.year,
            "isbn": book.isbn
        }
         serialized_books.append(serialized_book)

    return serialized_books

# for creating a book
@app.post("/books/", status_code=status.HTTP_201_CREATED)
async def create_book(book: bookbase, db: db_dependency):
    new_book = Book(**book.model_dump())
    db.add(new_book)
    db.commit()
    db.refresh(new_book)
    return {"message": "Book created successfully", "data": new_book}

#for fetching a specific book by ID
@app.get('/books/{book_id}',status_code=status.HTTP_200_OK)
async def fetch_book_id(book_id: int, db: db_dependency):
    book = db.query(Book).filter(Book.id == book_id).first()
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    serialized_book = {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "year": book.year,
            "isbn": book.isbn
        }
    return serialized_book

# To update a book in the database
@app.put("/books/{book_id}", status_code=status.HTTP_200_OK)
async def update_book(book_id: int, book: bookbase, db: db_dependency):
    book_to_update = db.query(Book).filter(Book.id == book_id).first()
    if book_to_update is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    for key, value in book.model_dump().items():
        setattr(book_to_update, key, value)
    db.commit()

    return {"message": "Book updated successfully", "data": book_to_update}

# To delete a book from the database
@app.delete("/books/{book_id}", status_code=status.HTTP_200_OK)
async def delete_book(book_id: int, db: db_dependency):
    book_to_delete = db.query(Book).filter(Book.id == book_id).first()
    if book_to_delete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    db.delete(book_to_delete)
    db.commit()
    return {"message": "Book deleted successfully"}
@app.get("/")
async def root():
    return {
        "app": "FYP Books API",
        "status": "running",
        "docs": "/docs",
        "books": "/books/",
        "health": "/health"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}
