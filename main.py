from typing import Annotated
from fastapi import Depends, FastAPI, Request, Path
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import ChecklistTemplate, ChecklistCategory, ChecklistSubcategory, ChecklistItem, ChecklistItemsToSubcategory, ChecklistVersion, ChecklistAnswer, ChecklistAnswersItem, ReportsPDF
from weasyprint import HTML
import json
import boto3
from botocore.exceptions import ClientError
import os
import asyncio
import uuid
app = FastAPI()
templates = Jinja2Templates(directory="templates")

sqs = boto3.client('sqs',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)
QUEUE_URL = os.getenv('SQS_QUEUE_URL')

s3 = boto3.client('s3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)
S3_BUCKET = os.getenv('S3_BUCKET_NAME')

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(process_sqs_messages())

async def process_sqs_messages():
    while True:
        try:
            print("Trying to receive messages from SQS...")
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                MessageAttributeNames=['All'],
                AttributeNames=['All']
            )
            
            print(f"SQS Response: {response}")

            if 'Messages' in response:
                print(f"Messages found: {len(response['Messages'])}")
                for message in response['Messages']:
                    try:
                        message_attributes = message.get('MessageAttributes', {})
                        if message_attributes.get('source', {}).get('StringValue') == 'report-service':
                            print("Ignoring message sent by this service")
                            sqs.delete_message(
                                QueueUrl=QUEUE_URL,
                                ReceiptHandle=message['ReceiptHandle']
                            )
                            continue

                        print(f"Processing message: {message['Body']}")
                        body = json.loads(message['Body'])
                        
                        db = SessionLocal()
                        
                        if all(key in body for key in ['versionId', 'inspectionId', 'assetId']):
                            inspection_id = body.get('inspectionId')
                            version_id = body.get('versionId')
                            asset_id = body.get('assetId')
                            print(f"Generating inspection report for inspection_id: {inspection_id}")
                            await generate_inspection_report_pdf(
                                Request(scope={'type': 'http'}),
                                db,
                                inspection_id,
                                version_id,
                                asset_id
                            )
                        elif 'templateId' in body:
                            template_id = body.get('templateId')
                            print(f"Generating checklist report for template_id: {template_id}")
                            await generate_checklist_report_pdf(
                                Request(scope={'type': 'http'}),
                                db,
                                template_id
                            )
                        else:
                            print("Message does not contain required parameters")

                        sqs.delete_message(
                            QueueUrl=QUEUE_URL,
                            ReceiptHandle=message['ReceiptHandle']
                        )
                        print("Message processed and deleted successfully")
                        
                    except Exception as e:
                        print(f"Error processing message: {str(e)}")
                        import traceback
                        traceback.print_exc()
                    finally:
                        db.close()
            else:
                print("No messages found")

        except Exception as e:
            print(f"Error reading from SQS: {str(e)}")
            import traceback
            traceback.print_exc()
        
        await asyncio.sleep(1)

async def upload_file_to_s3(file_path: str, s3_key: str, db: Session, template_id: str = None, inspection_id: str = None):
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET_NAME is not defined in environment variables")
            
        print(f"Starting upload to S3: {s3_key}")
        print(f"Bucket: {S3_BUCKET}")
        
        s3.upload_file(
            file_path,
            S3_BUCKET,
            s3_key,
            ExtraArgs={'ContentType': 'application/pdf'}
        )
        
        expiration = 604800
        signed_url = s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': s3_key
            },
            ExpiresIn=expiration
        )
        
        created_at = datetime.now()
        expires_at = created_at + timedelta(seconds=expiration)
        
        report_pdf = ReportsPDF(
            id=str(uuid.uuid4()),
            url=signed_url,
            name=s3_key.split('/')[-1],
            iat=created_at,
            exp=expires_at,
            status='ACTIVE',
            createdAt=created_at,
            updatedAt=expires_at
        )
        
        db.add(report_pdf)
        db.commit()
        
        print(f"Signed URL generated and registered in database: {signed_url}")
        print(f"Expires at: {expires_at}")
        
        await send_signed_url_to_sqs(signed_url, template_id, inspection_id)
        
        os.remove(file_path)
        print(f"Local file removed: {file_path}")
        
        return signed_url
        
    except ClientError as e:
        print(f"Error sending file to S3: {str(e)}")
        raise e
    except Exception as e:
        print(f"Unexpected error sending file to S3: {str(e)}")
        raise e

@app.post("/checklist-report/{template_id}/pdf")
async def generate_checklist_report_pdf(
    request: Request,
    db: db_dependency,
    template_id: str = Path(..., title="Template ID")
):
    try:
        print(f"Starting PDF generation for template_id: {template_id}")
        
        template = db.query(ChecklistTemplate)\
            .filter(ChecklistTemplate.id == template_id)\
            .first()
            
        if not template:
            print(f"Template not found for ID: {template_id}")
            return HTMLResponse(content="Template not found", status_code=404)

        print(f"Template found: {template.name}")

        version = db.query(ChecklistVersion)\
            .filter(ChecklistVersion.checklistId == template_id)\
            .order_by(ChecklistVersion.versionNumber.desc())\
            .first()

        if not version:
            print(f"Template version not found for template_id: {template_id}")
            return HTMLResponse(content="Template version not found", status_code=404)
        
        print(f"Version found: {version.versionNumber}")
        
        categories = db.query(ChecklistCategory)\
            .filter(ChecklistCategory.versionId == version.id)\
            .all()

        categories_data = []
        for category in categories:
            subcategories = db.query(ChecklistSubcategory)\
                .filter(ChecklistSubcategory.checklistCategoryId == category.id)\
                .all()

            subcategories_data = []
            for subcategory in subcategories:
                items = db.query(ChecklistItem)\
                    .join(
                        ChecklistItemsToSubcategory,
                        ChecklistItem.id == ChecklistItemsToSubcategory.checklistItemsId
                    )\
                    .filter(
                        ChecklistItemsToSubcategory.checklistSubcategoryId == subcategory.id
                    )\
                    .all()

                items_data = []
                for item in items:
                    items_data.append({
                        "id": item.id,
                        "title": item.title,
                        "description": item.description
                    })

                subcategories_data.append({
                    "id": subcategory.id,
                    "title": subcategory.title,
                    "description": subcategory.description,
                    "items": items_data
                })

            categories_data.append({
                "id": category.id,
                "title": category.title,
                "description": category.description,
                "subcategories": subcategories_data
            })

        template_data = {
            "request": request,
            "template": {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "created_at": template.createdAt.strftime("%d/%m/%Y %H:%M"),
                "updated_at": template.updatedAt.strftime("%d/%m/%Y %H:%M")
            },
            "categories": categories_data,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M")
        }

        print("Template data:", template_data)
        template_response = templates.TemplateResponse(
            "checklist.html",
            template_data
        )

        html_content = template_response.body.decode()
        pdf_path = f"checklist_{template_id}.pdf"
        
        print(f"Generating PDF at: {pdf_path}")
        HTML(string=html_content).write_pdf(pdf_path)
        print("PDF generated successfully!")

        s3_key = f"checklists/{template_id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        url = await upload_file_to_s3(pdf_path, s3_key, db, template_id=template_id)

        return {"url": url, "status": "success"}

    except Exception as e:
        print(f"Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"Error generating report: {str(e)}", status_code=500)

@app.post("/checklist-report/{inspection_id}/{version_id}/{asset_id}/pdf")
async def generate_inspection_report_pdf(
    request: Request,
    db: db_dependency,
    inspection_id: str = Path(..., title="Inspection ID"),
    version_id: str = Path(..., title="Version ID"),
    asset_id: str = Path(..., title="Asset ID")
):
    try:
        answers = db.query(ChecklistAnswersItem)\
            .join(ChecklistAnswer, ChecklistAnswersItem.checklistAnswersId == ChecklistAnswer.id)\
            .join(ChecklistItemsToSubcategory, ChecklistAnswersItem.subcategoryToItemId == ChecklistItemsToSubcategory.id)\
            .filter(
                ChecklistAnswer.routeId == inspection_id,
                ChecklistAnswer.versionId == version_id,
                ChecklistAnswer.assetId == asset_id
            )\
            .all()

        if not answers:
            return HTMLResponse(content="Answers not found", status_code=404)

        categories = db.query(ChecklistCategory)\
            .filter(ChecklistCategory.versionId == version_id)\
            .all()

        categories_data = []
        for category in categories:
            subcategories = db.query(ChecklistSubcategory)\
                .filter(ChecklistSubcategory.checklistCategoryId == category.id)\
                .all()

            subcategories_data = []
            for subcategory in subcategories:
                items_to_subcategory = db.query(ChecklistItemsToSubcategory)\
                    .filter(ChecklistItemsToSubcategory.checklistSubcategoryId == subcategory.id)\
                    .all()

                items_data = []
                for its in items_to_subcategory:
                    item = db.query(ChecklistItem)\
                        .filter(ChecklistItem.id == its.checklistItemsId)\
                        .first()

                    if item:
                        answer = next(
                            (a for a in answers if a.subcategoryToItemId == its.id),
                            None
                        )

                        items_data.append({
                            "id": item.id,
                            "title": item.title,
                            "description": item.description,
                            "answer": {
                                "value": answer.answer if answer else None,
                                "comment": answer.comment if answer else None,
                                "created_at": answer.createdAt.strftime("%d/%m/%Y %H:%M") if answer else None
                            } if answer else None
                        })

                subcategories_data.append({
                    "id": subcategory.id,
                    "title": subcategory.title,
                    "description": subcategory.description,
                    "items": items_data
                })

            categories_data.append({
                "id": category.id,
                "title": category.title,
                "description": category.description,
                "subcategories": subcategories_data
            })

        template = db.query(ChecklistTemplate)\
            .join(ChecklistVersion, ChecklistTemplate.id == ChecklistVersion.checklistId)\
            .filter(ChecklistVersion.id == version_id)\
            .first()

        if not template:
            return HTMLResponse(content="Template not found", status_code=404)

        template_data = {
            "template": {
                "name": template.name,
                "description": template.description
            },
            "inspection_id": inspection_id,
            "asset_id": asset_id,
            "categories": categories_data,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M")
        }

        template_response = templates.TemplateResponse(
            "checklist-checked.html",
            {"request": request, **template_data}
        )

        html_content = template_response.body.decode()

        pdf_path = f"inspection_{inspection_id}_{asset_id}.pdf"
        HTML(string=html_content).write_pdf(pdf_path)
        print("PDF generated successfully!")

        s3_key = f"inspections/{inspection_id}/{asset_id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        url = await upload_file_to_s3(pdf_path, s3_key, db, inspection_id=inspection_id)

        return {"url": url, "status": "success"}

    except Exception as e:
        print(f"Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"Error generating report: {str(e)}", status_code=500)

async def send_signed_url_to_sqs(url: str, template_id: str = None, inspection_id: str = None):
    try:
        message = {
            "url": url,
            "generated_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
            "source": "report-service"
        }

        if template_id:
            message["template_id"] = template_id
            message["type"] = "checklist"
        elif inspection_id:
            message["inspection_id"] = inspection_id
            message["type"] = "inspection"

        print(f"Sending message to SQS: {message}")
        
        response = sqs.send_message(
            QueueUrl=os.getenv('SQS_QUEUE_URL'),
            MessageBody=json.dumps(message),
            MessageAttributes={
                'type': {
                    'DataType': 'String',
                    'StringValue': 's3-upload'
                },
                'source': {
                    'DataType': 'String',
                    'StringValue': 'report-service'
                }
            }
        )
        
        print(f"Message sent successfully. MessageId: {response['MessageId']}")
        return True
        
    except Exception as e:
        print(f"Error sending message to SQS: {str(e)}")
        import traceback
        traceback.print_exc()
        return False