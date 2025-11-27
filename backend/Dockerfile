FROM python:3.11-slim
 
RUN apt-get update && apt-get install -y --no-install-recommends \

    ca-certificates \
&& update-ca-certificates \
&& apt-get clean && rm -rf /var/lib/apt/lists/*
 
WORKDIR /app
 

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
 

COPY . /app
EXPOSE 8000
 
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

 