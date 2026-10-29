/** Normalize a phone photo before uploading a small, square logo. */
export async function avatarBlob(file: File): Promise<Blob> {
  if (!['image/jpeg','image/png','image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024)
    throw new Error('Выберите JPG, PNG или WebP размером до 10 МБ');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    if (image.naturalWidth * image.naturalHeight > 16_000_000)
      throw new Error('Выберите изображение не больше 16 мегапикселей');
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 512;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Не удалось подготовить изображение');
    const side = Math.min(image.naturalWidth, image.naturalHeight);
    context.drawImage(image,(image.naturalWidth-side)/2,(image.naturalHeight-side)/2,side,side,0,0,512,512);
    const blob = await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/webp',0.9));
    if (!blob || blob.size > 1024 * 1024) throw new Error('Не удалось уменьшить изображение');
    return blob;
  } finally { URL.revokeObjectURL(url); }
}
