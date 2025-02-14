# Reports Generator

A FastAPI-based microservice for generating PDF reports from checklists and inspections with AWS integration.

## 🚀 Features

- PDF report generation from checklist templates
- Inspection report generation with answers
- AWS S3 integration for file storage
- AWS SQS integration for asynchronous processing
- Docker support
- Database integration with SQLAlchemy

## 🛠 Tech Stack

- Python 3.11+
- FastAPI
- SQLAlchemy
- WeasyPrint
- Jinja2
- AWS SDK (boto3)
- Docker
- PostgreSQL

## 📋 Prerequisites

- Python 3.11+
- PostgreSQL
- AWS Account (S3 and SQS access)
- Docker and Docker Compose (optional)

## 🔧 Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/reports-generator.git
cd reports-generator
```

2. Set up environment variables:

```bash
cp .env.example .env
```

Required environment variables:

```env
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=your_region
SQS_QUEUE_URL=your_sqs_url
S3_BUCKET_NAME=your_bucket_name
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

3. Install dependencies:

```bash
make install
```

## 🚀 Running the Application

### Using Docker:

```bash
docker-compose up --build
```

### Local Development:

```bash
make run
```

## 📚 API Documentation

### Generate Checklist Report

```http
POST /checklist-report/{template_id}/pdf
```

### Generate Inspection Report

```http
POST /checklist-report/{inspection_id}/{version_id}/{asset_id}/pdf
```

## 📁 Project Structure

```
reports-generator/
├── app/
│   ├── database.py    # Database configuration
│   └── models.py      # SQLAlchemy models
├── static/
│   └── checklist.css  # Report styling
├── templates/
│   ├── checklist.html
│   └── checklist-checked.html
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── main.py
├── Makefile
└── requirements.txt
```

## ⌨️ Development Commands

```bash
make install  # Install dependencies
make run      # Start development server
make clean    # Clean cache and generated PDFs
```

## 🔒 Security

- Environment variables for sensitive data
- AWS credentials management
- No hardcoded secrets

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ✍️ Author

Cristian Freitas
