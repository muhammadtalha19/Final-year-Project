FROM python:3.12-alpine

COPY . /

RUN pip install -r requirements.txt

WORKDIR /src

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
