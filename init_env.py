from cryptography.fernet import Fernet
from django.core.management.utils import get_random_secret_key


def generate_encryption_key():
    return Fernet.generate_key().decode("utf-8")


def generate_django_secret_key():
    return get_random_secret_key()


def main():
    credentials_key = generate_encryption_key()
    django_key = generate_django_secret_key()

    print(f"CREDENTIALS_ENCRYPTION_KEY={credentials_key}")
    print(f"DJANGO_SECRET_KEY={django_key}")
    print("AWS_RECORDING_STORAGE_BUCKET_NAME=")
    print("AWS_ACCESS_KEY_ID=")
    print("AWS_SECRET_ACCESS_KEY=")
    print("AWS_DEFAULT_REGION=us-east-1")
    print()
    print("# ASR Provider Configuration")
    print("ASR_PROVIDER=assemblyai  # options: assemblyai | deepgram")
    print("ASSEMBLYAI_API_KEY=")
    print("ASSEMBLYAI_REALTIME_URL=wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000")
    print()
    print("# Redis URL")
    print("REDIS_URL=redis://localhost:6379")


if __name__ == "__main__":
    main()
