"""Domain constants shared across RAG pipeline modules."""

# Mapping of critica keywords to search hint expansions
CRITICA_HINTS: dict[str, str] = {
    "critica 7": "procedimento principal incompativel com diagnostico principal CID compatibilidade",
    "critica 12": "diagnostico principal incompativel com sexo do paciente",
    "critica 13": "procedimento principal incompativel com idade do paciente",
    "critica 14": "sexo do paciente incompativel com procedimento principal",
    "critica 15": "procedimento principal nao permite permanencia",
    "050009": "numero da AIH nao informado",
    "050046": "procedimento principal incompativel com diagnostico principal",
    "050081": "diagnostico principal incompativel com sexo",
    "050083": "procedimento incompativel com idade",
    "050084": "sexo incompativel com procedimento",
    "050097": "procedimento nao permite permanencia",
}

# SIGTAP group code -> description
GRUPO_SIGTAP: dict[str, str] = {
    "01": "acoes de promocao e prevencao",
    "02": "procedimentos diagnosticos (exames)",
    "03": "procedimentos clinicos (consultas, fisioterapia)",
    "04": "procedimentos cirurgicos",
    "05": "transplantes de orgaos tecidos e celulas",
    "06": "medicamentos",
    "07": "orteses proteses e materiais especiais (OPM)",
    "08": "acoes complementares (UTI, diarias)",
}
