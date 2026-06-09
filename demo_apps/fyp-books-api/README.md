# Simple Book Management API

This is a simple RESTful API built with FastAPI for managing books. It allows you to perform basic CRUD (Create, Read, Update, Delete) operations on a collection of books stored in a database.

## Note
must have python installed if not fellow the guide [https://realpython.com/installing-python/]

## Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/martcpp/crud-api-fastapi.git
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   cd src 
   ```

3. **Run the application:**

   ```bash
   uvicorn app:app --reload
   ```

   The API will be available at `http://localhost:8000`.

## using docker
1. **Clone the repository:**

   ```bash
   git clone https://github.com/martcpp/crud-api-fastapi.git
   ```
   ```bash
   cd CRUD-API-FASTAPI
   ```

2. **Run the application:**

   ```bash
   docker build -t crud-api .
   docker run -p 8000:8000 crud-api
   ```

   The API will be available at `http://localhost:8000`

## Endpoints
`http://localhost:8000/docs` for more information about  the API documentation

### GET /books/

Retrieve all books.

### POST /books/

Create a new book. Send a JSON object with the book details in the request body.

Example Request Body:

```json
{
    "title": "Example Book",
    "author": "John Doe",
    "year": 2024,
    "isbn": "978-3-16-148410-0"
}
```

### GET /books/{book_id}

Retrieve a specific book by its ID.

### PUT /books/{book_id}

Update an existing book by its ID. Send a JSON object with the updated book details in the request body.

### DELETE /books/{book_id}

Delete a specific book by its ID.

## Data Schema

The following fields are available for a book:

- `id` (integer): Unique identifier for the book.
- `title` (string): Title of the book.
- `author` (string): Author of the book.
- `year` (integer): Year of publication.
- `isbn` (string): ISBN (International Standard Book Number) of the book.

## Dependencies

- FastAPI: Web framework for building APIs with Python.
- SQLAlchemy: SQL toolkit and Object-Relational Mapping (ORM) library for Python.
- uvicorn: ASGI server for running FastAPI applications.
- MySQL: MySQL server for running FastAPI applications with MySQL support enabled
- psycopg2 : for connecting to to postgresql databases
