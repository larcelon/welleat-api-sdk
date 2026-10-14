"""Extraction typée de valeurs JSON non typées, avec erreurs explicites."""

from welleat_api_sdk.errors import ResponseFormatError


def as_object(value: object, what: str) -> dict[str, object]:
    """Exige un objet JSON.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        L'objet JSON.

    Raises:
        ResponseFormatError: Si `value` n'est pas un objet.
    """
    if not isinstance(value, dict):
        raise ResponseFormatError(f"{what} : objet JSON attendu")
    return {str(key): item for key, item in value.items()}


def as_list(value: object, what: str) -> list[object]:
    """Exige une liste JSON.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        La liste JSON.

    Raises:
        ResponseFormatError: Si `value` n'est pas une liste.
    """
    if not isinstance(value, list):
        raise ResponseFormatError(f"{what} : liste JSON attendue")
    return list(value)


def as_str(value: object, what: str) -> str:
    """Exige une chaîne non vide.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        La chaîne.

    Raises:
        ResponseFormatError: Si `value` n'est pas une chaîne non vide.
    """
    if not isinstance(value, str) or not value:
        raise ResponseFormatError(f"{what} : chaîne non vide attendue")
    return value


def as_device_id(value: object, what: str) -> str | int:
    """Exige un identifiant à type mixte : entier ou chaîne non vide, conservé tel quel.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        L'identifiant, sans conversion.

    Raises:
        ResponseFormatError: Si `value` n'est ni un entier (hors booléen) ni une chaîne non vide.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value:
        return value
    raise ResponseFormatError(f"{what} : entier ou chaîne non vide attendu")


def as_int(value: object, what: str) -> int:
    """Exige un entier, ou une chaîne décimale ; les booléens sont refusés.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        L'entier.

    Raises:
        ResponseFormatError: Si `value` n'est pas convertible en entier.
    """
    if isinstance(value, bool):
        raise ResponseFormatError(f"{what} : entier attendu, pas un booléen")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value)
    raise ResponseFormatError(f"{what} : entier attendu")


def as_float(value: object, what: str) -> float:
    """Exige un nombre ; les booléens sont refusés.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        Le nombre.

    Raises:
        ResponseFormatError: Si `value` n'est pas un nombre.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ResponseFormatError(f"{what} : nombre attendu")
    return float(value)


def as_bool(value: object, what: str) -> bool:
    """Exige un booléen.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        Le booléen.

    Raises:
        ResponseFormatError: Si `value` n'est pas un booléen.
    """
    if not isinstance(value, bool):
        raise ResponseFormatError(f"{what} : booléen attendu")
    return value
