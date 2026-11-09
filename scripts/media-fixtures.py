"""Generate synthetic E2E assets. Audio is a test tone, NOT human narration."""
import math
import struct
import wave
from pathlib import Path
from PIL import Image, ImageDraw

root = Path('.data/e2e/assets')
root.mkdir(parents=True, exist_ok=True)
image = Image.new('RGB', (1000, 700), '#ecf3ef')
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((100, 90, 900, 610), radius=32, fill='white', outline='#93b8a6', width=4)
for x, color in [(230, '#1b8065'), (490, '#caa96b'), (750, '#7199b2')]:
    draw.rounded_rectangle((x-70, 250, x+70, 390), radius=22, fill=color)
for x in (350, 610):
    draw.line((x, 320, x+70, 320), fill='#889e94', width=8)
    draw.polygon([(x+70, 320), (x+48, 305), (x+48, 335)], fill='#889e94')
draw.text((130, 130), 'FROM IDEA TO EXPLANATION', fill='#305547', font_size=32)
image.save(root / 'workflow.png')
with wave.open(str(root / 'narration-tone.wav'), 'wb') as audio:
    audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
    audio.writeframes(b''.join(struct.pack('<h', int(1500*math.sin(2*math.pi*440*n/24000)))
                               for n in range(24000*3)))
print('Created workflow.png and a 3-second 440Hz test tone (not narration).')
