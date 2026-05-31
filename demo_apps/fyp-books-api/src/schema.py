from pydantic import BaseModel

class bookbase(BaseModel):
    """
    validate the input data from api end point and return the data
    """
    title : str
    author : str
    year  : int
    isbn  : str