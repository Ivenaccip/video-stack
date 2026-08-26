"""Selección de encoder de video con fallback: NVENC → Quick Sync → AMF → CPU.

La prueba es FUNCIONAL y por juego completo de args, no por listado: que el
encoder aparezca en `ffmpeg -encoders` no basta (un driver viejo frente a un
ffmpeg nuevo lo lista y aun así falla al codificar), y un backend puede tener
h264 pero no HEVC 10-bit — por eso preview y final se resuelven por separado.
"""

import subprocess

# Escala de preview/proxy compartida por make_proxy y render_cuts: acota el cuadro
# a 1280 por su lado largo SOLO hacia abajo — fijar el ancho (scale=1280:-2)
# upscaleaba el metraje vertical (1080x1920 -> 1280x2276) y el horizontal chico.
PREVIEW_VF = ("scale=w='min(1280,iw)':h='min(1280,ih)'"
              ":force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p")

# 640x360, no menos: AMF rechaza resoluciones diminutas (~<128px) con "Init failed
# error 5", así que un probe de 64x64 da falso negativo en máquinas AMD.
_PROBE_SRC = ["-f", "lavfi", "-i", "color=black:size=640x360:rate=30:duration=0.1"]

# (nombre, args de encoder, hwaccel de decodificación)
_CANDIDATES = {
    "preview": [
        ("NVENC (GPU NVIDIA)",
         ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "30", "-b:v", "0"],
         ["-hwaccel", "cuda"]),
        ("Quick Sync (Intel)",
         ["-c:v", "h264_qsv", "-preset", "fast", "-global_quality", "30"],
         []),
        ("AMF (GPU AMD)",
         ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp",
          "-qp_i", "30", "-qp_p", "30"],
         []),
        ("CPU (libx264)",
         ["-c:v", "libx264", "-preset", "fast", "-crf", "26"],
         []),
    ],
    "final": [
        ("NVENC (GPU NVIDIA)",
         ["-c:v", "hevc_nvenc", "-preset", "p5", "-profile:v", "main10",
          "-pix_fmt", "p010le", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
         ["-hwaccel", "cuda"]),
        ("Quick Sync (Intel)",
         ["-c:v", "hevc_qsv", "-preset", "medium", "-profile:v", "main10",
          "-pix_fmt", "p010le", "-global_quality", "19"],
         []),
        ("AMF (GPU AMD)",
         ["-c:v", "hevc_amf", "-quality", "quality", "-rc", "cqp",
          "-qp_i", "19", "-qp_p", "19", "-profile:v", "main10", "-pix_fmt", "p010le"],
         []),
        ("CPU (libx265)",
         ["-c:v", "libx265", "-preset", "medium", "-profile:v", "main10",
          "-pix_fmt", "yuv420p10le", "-crf", "19"],
         []),
    ],
}


def _probe(enc_args: list[str]) -> bytes | None:
    """None si codifica; el stderr del intento si falla."""
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *_PROBE_SRC,
                        *enc_args, "-f", "null", "-"], capture_output=True)
    return None if r.returncode == 0 else r.stderr


def select(mode: str) -> tuple[list[str], list[str]]:
    """(enc_args, hwaccel) del primer backend de la cadena que codifica en esta
    máquina. mode: "preview" (h264) o "final" (HEVC 10-bit)."""
    for name, enc_args, hwaccel in _CANDIDATES[mode]:
        err = _probe(enc_args)
        if err is None:
            slow = " — sin aceleración por hardware, más lento" if name.startswith("CPU") else ""
            print(f"encoder {mode}: {name}{slow}")
            return enc_args, hwaccel
        # Los casos más comunes de "hay GPU pero cae a CPU": driver más viejo que
        # el ffmpeg. Sin la pista, el alumno nunca sabe que le falta un update.
        if b"Driver does not support the required nvenc API" in err:
            print("GPU NVIDIA presente pero su driver es más viejo de lo que este "
                  "ffmpeg necesita — actualiza el driver NVIDIA para acelerar renders")
        elif b"not supported by AMD GPU drivers" in err:
            print("GPU AMD presente pero su driver es más viejo de lo que este modo "
                  "necesita — actualiza el driver AMD (Adrenalin) para acelerarlo")
    raise SystemExit("ffmpeg no pudo codificar con ningún encoder (¿instalación rota? "
                     "prueba `ffmpeg -version`)")
