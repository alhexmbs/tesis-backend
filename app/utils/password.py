from pwdlib import PasswordHash
from zxcvbn import zxcvbn

password_hash = PasswordHash.recommended()


def validate_password_strength(password, user_data=None):
    if len(password) < 8 or len(password) > 50:
        raise ValueError("La contraseña debe tener entre 8 y 50 caracteres.")

    # user_data debería ser una lista opcional, ej: ['juan_perez', 'juan@email.com']
    inputs = user_data if user_data else []
    results = zxcvbn(password, user_inputs=inputs)

    score = results.get("score", 0)  # 0 (débil) a 4 (fuerte)

    if score < 3:
        feedback = results.get("feedback", {})
        warning = feedback.get("warning", "")
        suggestions = " ".join(feedback.get("suggestions", []))

        # Fallback en caso de que warning/suggestions vengan vacíos
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
