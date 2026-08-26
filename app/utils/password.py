from pwdlib import PasswordHash
from zxcvbn import zxcvbn

password_hash = PasswordHash.recommended()

def validate_password_strength(password):
    if len(password) > 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")

    results = zxcvbn(password, user_inputs=password)
    score = results.get("score", 0) # Returns an integer 0 (weak) to 4 (strong)

    # Enforce a minimum acceptable score (e.g., 3 out of 4)
    if score < 3:
        # Extract localized feedback hints if available from the library
        feedback = results.get("feedback", {})
        warning = feedback.get("warning", "Password is too easy to guess.")
        suggestions = " ".join(feedback.get("suggestions", []))
        
        raise ValueError(f"{warning} {suggestions}".strip())

    return score

def hash_password(password):
    hash = password_hash.hash(password)
    return hash

def verify_password(user_password, hashed_password):
    verification = password_hash.verify(user_password, hashed_password)
    return verification