"""
Mapeia automaticamente cada crítica do processos-criticas para as seções
relevantes do Manual SIH/SUS, gerando uma referência cruzada.
"""

import json
import re
import sys
from pathlib import Path

import chromadb
from rich.console import Console
from rich.table import Table
from sentence_transformers import SentenceTransformer

console = Console()

# Extrair críticas do arquivo TypeScript
CRITICAS_TS = Path(__file__).parent.parent.parent / "processos-criticas" / "src" / "constants" / "criticas.ts"


def extrair_criticas_do_ts() -> list[dict]:
    """Lê o arquivo criticas.ts e extrai código + nome de cada crítica."""
    if not CRITICAS_TS.exists():
        console.print(f"[red]Arquivo não encontrado: {CRITICAS_TS}[/red]")
        sys.exit(1)

    conteudo = CRITICAS_TS.read_text(encoding="utf-8")

    # Pattern: CRITICA_N: { codigo: '...', nome: '...', campos: [...] }
    pattern = re.compile(
        r"CRITICA_(\d+):\s*\{\s*"
        r"codigo:\s*'(\d+)'\s*,\s*"
        r"nome:\s*'([^']+)'\s*,",
        re.MULTILINE,
    )

    criticas = []
    for match in pattern.finditer(conteudo):
        criticas.append(
            {
                "numero": int(match.group(1)),
                "codigo": match.group(2),
                "nome": match.group(3),
            }
        )

    criticas.sort(key=lambda c: c["numero"])
    return criticas


def mapear_para_manual(
    criticas: list[dict],
    model: SentenceTransformer,
    collection,
) -> list[dict]:
    """Para cada crítica, busca as seções mais relevantes do manual."""
    resultados = []

    for critica in criticas:
        # Construir query semântica a partir do nome da crítica
        query = critica["nome"]

        # Enriquecer queries específicas
        enrichments = {
            "incompatível com diagnóstico": "compatibilidade CID procedimento SIGTAP",
            "incompatível com sexo": "sexo paciente compatibilidade procedimento diagnóstico",
            "incompatível com idade": "idade paciente compatibilidade procedimento faixa etária",
            "permanência": "dias permanência média diárias SIGTAP",
            "duplicidade": "duplicidade AIH mesmo paciente reinternação 03 dias",
            "AIH não informado": "número AIH numeração emissão",
            "data da saída": "data saída internação alta competência",
            "data da internação": "data internação autorização emissão AIH",
            "procedimento solicitado": "procedimento solicitado realizado mudança",
            "procedimento realizado": "procedimento principal realizado SIGTAP",
            "CNS": "cartão nacional saúde CNS paciente",
            "CBO": "classificação brasileira ocupações CBO médico CNES",
            "OPM": "órteses próteses materiais especiais OPM compatibilidade",
            "leito": "especialidade leito CNES cadastro",
            "diária": "diária acompanhante UTI UCI permanência",
            "anestesia": "anestesia regional geral sedação cirurgião",
            "hemoterapia": "hemoterapia transfusão sangue agência",
            "transplante": "transplante órgãos doação retirada",
            "politraumatizado": "politraumatizado cirurgia múltipla tratamento",
            "obstetrícia": "obstetrícia parto cesariana gestante",
            "recém-nascido": "recém-nascido RN parto pediatria",
            "habilitação": "habilitação estabelecimento CNES",
            "autorizador": "profissional autorizador solicitante executante",
            "diretor clínico": "diretor clínico assinatura responsável",
            "município": "município UF endereço paciente IBGE",
            "raça": "raça cor etnia indígena",
            "caráter": "caráter atendimento eletivo urgência",
            "mudança": "mudança procedimento clínica cirurgia",
        }

        for key, extra in enrichments.items():
            if key.lower() in query.lower():
                query = f"{query} {extra}"
                break

        embedding = model.encode([query], normalize_embeddings=True)
        resultado = collection.query(
            query_embeddings=[embedding[0].tolist()],
            n_results=3,
            include=["metadatas", "distances"],
        )

        secoes_encontradas = []
        for i in range(len(resultado["ids"][0])):
            meta = resultado["metadatas"][0][i]
            score = 1 - resultado["distances"][0][i]
            secoes_encontradas.append(
                {
                    "secao": meta["secao"],
                    "titulo": meta["titulo"],
                    "pagina": meta["pagina"],
                    "relevancia": round(score, 3),
                }
            )

        resultados.append(
            {
                **critica,
                "secoes_manual": secoes_encontradas,
            }
        )

    return resultados


def main():
    console.print("\n[bold blue]Mapeamento Críticas x Manual SIH/SUS[/bold blue]\n")

    # 1. Extrair críticas
    console.print("[dim]Lendo críticas do processos-criticas...[/dim]")
    criticas = extrair_criticas_do_ts()
    console.print(f"  {len(criticas)} críticas encontradas\n")

    # 2. Carregar sistema RAG
    db_dir = Path(__file__).parent / "db"
    if not db_dir.exists():
        console.print("[red]Banco vetorial não encontrado. Execute setup.sh primeiro.[/red]")
        sys.exit(1)

    console.print("[dim]Carregando modelo de embeddings...[/dim]")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    client = chromadb.PersistentClient(path=str(db_dir))
    collection = client.get_collection("manual_sih")

    # 3. Mapear
    console.print("[dim]Mapeando críticas para seções do manual...[/dim]\n")
    mapeamento = mapear_para_manual(criticas, model, collection)

    # 4. Exibir tabela
    table = Table(title="Referência Cruzada: Críticas x Manual SIH/SUS", show_lines=True)
    table.add_column("Crítica", style="cyan", width=8)
    table.add_column("Código", style="dim", width=8)
    table.add_column("Nome", style="white", width=45)
    table.add_column("Seção Manual", style="green", width=50)

    for item in mapeamento:
        secoes_str = "\n".join(
            f"§{s['secao']} {s['titulo'][:40]} (p.{s['pagina']}) [{s['relevancia']:.0%}]"
            for s in item["secoes_manual"]
        )
        table.add_row(
            str(item["numero"]),
            item["codigo"],
            item["nome"],
            secoes_str,
        )

    console.print(table)

    # 5. Salvar JSON
    output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "mapeamento_criticas_manual.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mapeamento, f, ensure_ascii=False, indent=2)

    console.print(f"\n[green]Mapeamento salvo em: {output_path}[/green]")

    # 6. Estatísticas
    alta_relevancia = sum(
        1
        for m in mapeamento
        if m["secoes_manual"] and m["secoes_manual"][0]["relevancia"] > 0.5
    )
    console.print(f"\n[bold]Estatísticas:[/bold]")
    console.print(f"  Total de críticas: {len(mapeamento)}")
    console.print(
        f"  Com alta relevância (>50%): {alta_relevancia} ({alta_relevancia/len(mapeamento):.0%})"
    )


if __name__ == "__main__":
    main()
