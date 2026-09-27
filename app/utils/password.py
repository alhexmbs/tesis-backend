from pwdlib import PasswordHash
from zxcvbn import zxcvbn

password_hash = PasswordHash.recommended()


# Diccionario básico con los mensajes más comunes de zxcvbn
TRADUCCIONES = {
    "This is a very common password.": "Esta es una contraseña muy común.",
    "This is similar to a commonly used password.": "Esta contraseña es muy similar a otras de uso común.",
    "A word by itself is easy to guess": "Una sola palabra es fácil de adivinar.",
    "Add another word or two. Uncommon words are better.": "Agrega una o dos palabras más. Las palabras inusuales son mejores.",
    "Predictable substitutions like '@' instead of 'a' don't help much": "Sustituciones predecibles como '@' en lugar de 'a' no ayudan mucho.",
    "Capitalization doesn't help very much": "Usar mayúsculas no ayuda mucho.",
    "All-uppercase is almost as easy to guess as all-lowercase": "Usar solo mayúsculas es tan fácil de adivinar como usar solo minúsculas.",
    "This is a top-10 common password.": "Esta es una de las 10 contraseñas más comunes.",
}


def validate_password_strength(password, user_data=None):
    if len(password) < 8 or len(password) > 128:
        raise ValueError("La contraseña debe tener entre 8 y 128 caracteres.")

    inputs = user_data if user_data else []
    results = zxcvbn(password, user_inputs=inputs)
    score = results.get("score", 0)

    if score < 3:
        feedback = results.get("feedback", {})

        # Obtener los textos en inglés
        raw_warning = feedback.get("warning", "")
        raw_suggestions = feedback.get("suggestions", [])

        # Traducir (si no existe en el diccionario, devuelve el texto original temporalmente)
        warning = TRADUCCIONES.get(raw_warning, raw_warning)
        suggestions = " ".join([TRADUCCIONES.get(s, s) for s in raw_suggestions])

        error_msg = f"{warning} {suggestions}".strip()

        if not error_msg:
            error_msg = "La contraseña es demasiado fácil de adivinar."

        raise ValueError(error_msg)

    return score


def hash_password(password):
    hash = password_hash.hash(password)
    return hash


def verify_password(user_password, hashed_password):
    verification = password_hash.verify(user_password, hashed_password)
    return verification
