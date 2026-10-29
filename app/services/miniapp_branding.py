"""Small persistent Mini App logo, independent of the Telegram bot profile."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError
from app.database import Database

MAX_AVATAR_BYTES = 1024 * 1024


class MiniAppBranding:
    def __init__(self, database: Database):
        self.database = database
        self.root = database.path.parent / 'branding'

    def avatar_url(self):
        with self.database.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='miniapp.avatar'").fetchone()
        if row and self.path(row['value']).is_file():
            return '/api/branding/avatar/' + row['value'] + '.webp'
        return '/brand/avatar.jpg'

    def path(self, key):
        if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid avatar key')
        return self.root / (key + '.webp')

    def save(self, data: bytes):
        if not data or len(data) > MAX_AVATAR_BYTES:
            raise ValueError('Изображение должно быть не больше 1 МБ')
        try:
            with Image.open(BytesIO(data)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 16_000_000:
                    raise ValueError('Выберите JPG, PNG или WebP не больше 16 мегапикселей')
                image = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGBA'), (256, 256), method=Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format='WEBP', quality=90)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError('Не удалось прочитать изображение. Выберите JPG, PNG или WebP') from error
        encoded = output.getvalue()
        key = sha256(encoded).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path(key)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as file:
                temporary = Path(file.name)
                file.write(encoded)
            os.replace(temporary, target)
            with self.database.connect() as db:
                db.execute("""INSERT INTO settings(key,value) VALUES('miniapp.avatar',?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""", (key,))
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        # Retain recent versions for already-open clients while bounding storage.
        for old in sorted(self.root.glob('*.webp'), key=lambda p:p.stat().st_mtime, reverse=True)[10:]:
            if old != target:
                old.unlink(missing_ok=True)
        return self.avatar_url()
