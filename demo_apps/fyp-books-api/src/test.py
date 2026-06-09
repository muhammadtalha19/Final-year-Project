from fastapi.testclient import TestClient
from app import app  
client = TestClient(app)

# Test case for fetching books
def test_fetch_books():
    response = client.get("/books/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    
    for book in response.json():
        assert "id" in book
        assert "title" in book
        assert "author" in book
        assert "year" in book
        assert "isbn" in book

# Test case for creating a book
def test_create_book():
    book_data = {
        "title": "Test Book",
        "author": "Test Author",
        "year": 2022,
        "isbn": "1234567890"
    }
    response = client.post("/books/", json=book_data)
    assert response.status_code == 201
    assert "message" in response.json()

# Test case for fetching a specific book by ID
def test_fetch_book_by_id():
    response = client.get("/books/1")
    assert response.status_code == 404

# Test case for updating a book
def test_update_book():
    book_data = {
        "title": "Updated Book",
        "author": "Updated Author",
        "year": 2023,
        "isbn": "0987654321"
    }
    response = client.put("/books/1", json=book_data)
    assert response.status_code == 404

# Test case for deleting a book
def test_delete_book():
    response = client.delete("/books/1")
    assert response.status_code == 404

# Test case for creating a book and fetching it by ID
def test_create_and_fetch_book():
    book_data = {
        "title": "New Book",
        "author": "New Author",
        "year": 2023,
        "isbn": "9876543210"
    }
    response = client.post("/books/", json=book_data)
    assert response.status_code == 201
    new_book_id = response.json().get("id")
    
    if new_book_id:
        fetch_response = client.get(f"/books/{new_book_id}")
        assert fetch_response.status_code == 200
        assert fetch_response.json()["title"] == book_data["title"]

# Test case for updating an existing book
def test_update_existing_book():
    book_data = {
        "title": "Existing Book",
        "author": "Existing Author",
        "year": 2020,
        "isbn": "1234567890"
    }
    response = client.post("/books/", json=book_data)
    assert response.status_code == 201
    existing_book_id = response.json().get("id")
    
    if existing_book_id:
        update_data = {
            "title": "Updated Existing Book",
            "author": "Updated Existing Author",
            "year": 2021,
            "isbn": "0987654321"
        }
        update_response = client.put(f"/books/{existing_book_id}", json=update_data)
        assert update_response.status_code == 200



def test_delete_existing_book():
    book_data = {
        "title": "Book to Delete",
        "author": "Author to Delete",
        "year": 2021,
        "isbn": "1357924680"
    }
    response = client.post("/books/", json=book_data)
    assert response.status_code == 201
    book_to_delete_id = response.json().get("id")


    if book_to_delete_id:
        delete_response = client.delete(f"/books/{book_to_delete_id}")
        assert delete_response.status_code == 200
