# AWS EC2 Backup and Recovery Using Amazon S3

A beginner-friendly Flask application that demonstrates backing up files explicitly selected and uploaded through a web dashboard, then restoring them by downloading a copy. It can store files in Amazon S3 with Boto3 or use a local simulation when AWS is not configured.

> This project does not automatically back up an EC2 instance, disk, or server. Only files a user explicitly uploads through this application are backed up.

## Features

- Responsive dashboard with storage mode, backup count, last backup, and backup history.
- Upload, restore/download, and delete operations.
- A confirmation prompt before deleting a backup.
- Automatic local simulation when a bucket or usable AWS credentials are unavailable.
- File size limit of 16 MB, sanitized names, generated object keys, health check, and basic API error handling.
- No AWS credentials in source code or browser code.

## Architecture

```text
Browser (HTML, CSS, JavaScript)
        | JSON / multipart upload / file download
        v
Flask application (app.py)
        |                         |
        | Boto3 + credential chain | Local simulation storage
        v                         v
Amazon S3 bucket             backups/ directory
```

The Flask storage adapter selects S3 when `S3_BUCKET_NAME` is configured and Boto3 can find credentials through the standard AWS credential chain. Otherwise, files are written beneath `backups/` and the dashboard visibly identifies simulation mode. The browser communicates only with Flask; credentials remain on the server side.

## Prerequisites

- Windows 10/11 (the commands below use PowerShell), macOS, or Linux.
- Python 3.10 or newer and Git.
- An AWS account and an S3 bucket only for real S3 mode.

## Installation and local simulation

Open PowerShell in the `aws-backup-recovery` project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. When `S3_BUCKET_NAME` is not set, the app uses local simulation automatically, whether or not AWS credentials are present. Uploaded files are stored in `backups/`; this generated content is excluded from Git. Stop the server with `Ctrl+C`.

If PowerShell blocks virtual-environment activation, run the interpreter directly instead:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Configuration for Amazon S3

Set the bucket and AWS region in the server environment before starting Flask. Do not put access keys in this project, in frontend code, or in a committed `.env` file.

```powershell
$env:AWS_REGION = "us-east-1"
$env:S3_BUCKET_NAME = "your-unique-bucket-name"
python app.py
```

Replace the region and bucket name with your values. Provide credentials through the standard AWS credential chain, for example an AWS CLI profile (`aws configure`), environment variables supplied by your deployment platform, or an EC2 instance profile. For a named profile in PowerShell, set `$env:AWS_PROFILE = "your-profile"`. Never commit AWS credentials.

When a bucket is configured but Boto3 cannot resolve credentials, the application falls back to simulation mode. If credentials resolve but the identity lacks S3 access, the app stays in S3 mode and reports operation errors on the dashboard.

### AWS setup

1. In the AWS console, create an S3 bucket in the region you plan to use. Keep public access blocked and enable default encryption.
2. Use an IAM identity or EC2 instance role for the application. Grant only the required permissions on this bucket: `s3:ListBucket` on the bucket ARN and `s3:PutObject`, `s3:GetObject`, and `s3:DeleteObject` on `bucket-arn/*`.
3. Configure that identity through the AWS CLI profile, environment provided securely by your host, or EC2 instance profile. Do not add credentials to the repository.
4. Set `AWS_REGION` and `S3_BUCKET_NAME` in the same environment as the Flask process, then restart the app.
5. Confirm the dashboard says **Amazon S3 connected**. Upload a small test file and verify its object appears in the bucket. The dashboard delete action removes that object after confirmation.

The application does not configure bucket policies, create buckets, enable versioning, or manage EC2 backups. Set any organization-specific retention and encryption controls in AWS separately.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Dashboard |
| `GET` | `/health` | Health and selected storage mode |
| `GET` | `/api/status` | Storage mode, backup count, and latest upload time |
| `GET` | `/api/backups` | Backup history |
| `POST` | `/api/backups` | Upload a file (`multipart/form-data`, field name `file`) |
| `GET` | `/api/backups/<key>/restore` | Download a backup |
| `DELETE` | `/api/backups/<key>` | Delete a backup |

## Tests

Run the backend tests from the project directory:

```powershell
python -m pytest -q
```

Tests force simulation mode and use a temporary directory. They do not connect to or delete objects in an actual S3 bucket.

## Screenshots to capture

For a project report or GitHub README, capture:

1. The initial dashboard in simulation mode with the local simulation banner visible.
2. The dashboard after uploading a sample file, showing the backup count and history row.
3. The confirmation dialog shown before deleting a backup.
4. The dashboard in S3 mode after setting AWS configuration (hide account IDs, bucket names, and other private details).
5. A successful restored file download in the browser.

Do not include credentials, secret values, personal data, or sensitive AWS account details in screenshots.

## Git and GitHub

Create an empty GitHub repository first, without initializing it with a README or license. Then run these commands from the project directory, replacing the URL with the new repository URL:

```powershell
git init
git add .
git status
git commit -m "Create AWS backup and recovery demo"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

Review `git status` before committing. `.gitignore` excludes virtual environments, environment files, credentials, test output, and generated backup files. Never force-add secrets or real customer backup data.