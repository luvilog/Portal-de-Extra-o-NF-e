"""
LUVI LOG — Extrator de Chave de Acesso NF-e
Backend FastAPI que recebe fotos e extrai a chave via Gemini.
"""

import os
import re
import json

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from google import genai
from google.genai import types

app = FastAPI(title="LUVI LOG — Extrator de Chave NF-e")

# ── Cliente Gemini (inicializa uma vez) ──────────────────
gemini_client = None


def get_gemini_client():
    global gemini_client
    if gemini_client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não configurada")
        gemini_client = genai.Client(api_key=api_key)
    return gemini_client


# ── Prompt de extração ───────────────────────────────────
PROMPT = """Analise esta imagem de um DANFE (Documento Auxiliar da Nota Fiscal Eletrônica) 
ou Nota Fiscal e extraia a CHAVE DE ACESSO de 44 dígitos numéricos.

A chave geralmente aparece abaixo do código de barras ou no topo do documento,
formatada em blocos de 4 dígitos.

Responda SOMENTE com JSON puro, sem markdown, sem crases:
{"encontrou": true, "chave_acesso": "44 dígitos sem espaços", "confianca": "alta/media/baixa"}

Se não encontrar:
{"encontrou": false, "chave_acesso": null, "confianca": null}"""


# ── Validação da chave ───────────────────────────────────
def validar_chave(chave: str) -> bool:
    if not chave or len(chave) != 44 or not chave.isdigit():
        return False

    ufs = {
        "11","12","13","14","15","16","17",
        "21","22","23","24","25","26","27","28","29",
        "31","32","33","35","41","42","43",
        "50","51","52","53",
    }
    if chave[:2] not in ufs:
        return False
    if chave[20:22] not in ("55", "65", "57"):
        return False

    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(chave[:43])))
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return int(chave[43]) == dv


def decodificar_chave(chave: str) -> dict:
    modelos = {"55": "NF-e", "65": "NFC-e", "57": "CT-e"}
    return {
        "uf": chave[0:2],
        "ano_mes": f"20{chave[2:4]}/{chave[4:6]}",
        "cnpj": f"{chave[6:8]}.{chave[8:11]}.{chave[11:14]}/{chave[14:18]}-{chave[18:20]}",
        "modelo": modelos.get(chave[20:22], chave[20:22]),
        "serie": str(int(chave[22:25])),
        "numero_nf": str(int(chave[25:34])),
    }


def formatar_chave(chave: str) -> str:
    return " ".join(chave[i : i + 4] for i in range(0, 44, 4))


# ── Página principal (HTML embutido) ─────────────────────
PAGINA_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    <title>LUVI LOG — Extrator de Chave NF-e</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --azul: #1a3a6b;
            --azul-claro: #2c5aa0;
            --dourado: #c9a84c;
            --creme: #faf8f3;
            --cinza: #6b7280;
            --verde: #16a34a;
            --vermelho: #dc2626;
            --sombra: 0 2px 12px rgba(0,0,0,0.08);
        }
        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: var(--creme);
            color: #1f2937;
            min-height: 100dvh;
            display: flex;
            flex-direction: column;
        }
        header {
            background: var(--azul);
            color: white;
            padding: 1.25rem 1.5rem;
            text-align: center;
        }
        header h1 { font-size: 1.35rem; font-weight: 700; letter-spacing: 0.5px; }
        header p { font-size: 0.8rem; opacity: 0.7; margin-top: 0.25rem; }
        main {
            flex: 1;
            padding: 1.5rem;
            max-width: 540px;
            margin: 0 auto;
            width: 100%;
        }
        .upload-area {
            border: 2px dashed #d1d5db;
            border-radius: 12px;
            padding: 2.5rem 1.5rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
            background: white;
        }
        .upload-area:hover, .upload-area.dragover {
            border-color: var(--azul-claro);
            background: #f0f4ff;
        }
        .upload-area svg {
            width: 48px; height: 48px; color: var(--cinza); margin-bottom: 0.75rem;
        }
        .upload-area h2 { font-size: 1rem; font-weight: 600; color: #374151; }
        .upload-area p { font-size: 0.8rem; color: var(--cinza); margin-top: 0.35rem; }
        .btn-camera {
            display: inline-block; margin-top: 1rem; padding: 0.7rem 1.5rem;
            background: var(--azul); color: white; border: none; border-radius: 8px;
            font-size: 0.9rem; font-weight: 600; cursor: pointer;
        }
        .btn-camera:active { transform: scale(0.97); }
        input[type="file"] { display: none; }
        .preview {
            display: none; margin-top: 1.25rem; border-radius: 12px;
            overflow: hidden; background: white; box-shadow: var(--sombra);
        }
        .preview img { width: 100%; max-height: 280px; object-fit: cover; }
        .preview-bar {
            display: flex; justify-content: space-between; align-items: center;
            padding: 0.75rem 1rem;
        }
        .preview-bar span { font-size: 0.8rem; color: var(--cinza); }
        .btn-trocar {
            font-size: 0.8rem; color: var(--azul-claro); background: none;
            border: none; cursor: pointer; font-weight: 600;
        }
        .loading { display: none; text-align: center; margin-top: 2rem; }
        .spinner {
            width: 36px; height: 36px; border: 3px solid #e5e7eb;
            border-top-color: var(--azul); border-radius: 50%;
            animation: spin 0.7s linear infinite; margin: 0 auto 0.75rem;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .loading p { font-size: 0.85rem; color: var(--cinza); }
        .resultado { display: none; margin-top: 1.5rem; }
        .card {
            background: white; border-radius: 12px;
            box-shadow: var(--sombra); overflow: hidden;
        }
        .card-header {
            padding: 1rem 1.25rem; display: flex; align-items: center; gap: 0.6rem;
        }
        .card-header.sucesso { background: #f0fdf4; border-bottom: 1px solid #bbf7d0; }
        .card-header.erro { background: #fef2f2; border-bottom: 1px solid #fecaca; }
        .badge {
            font-size: 0.7rem; font-weight: 600; padding: 0.2rem 0.6rem;
            border-radius: 20px; text-transform: uppercase;
        }
        .badge.ok { background: #dcfce7; color: #166534; }
        .badge.falha { background: #fee2e2; color: #991b1b; }
        .badge.aviso { background: #fef9c3; color: #854d0e; }
        .card-header span { font-size: 0.85rem; font-weight: 500; }
        .chave-box { padding: 1.25rem; }
        .chave-label {
            font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px;
            color: var(--cinza); font-weight: 600; margin-bottom: 0.5rem;
        }
        .chave-valor {
            font-family: 'Courier New', monospace; font-size: 0.95rem; font-weight: 600;
            color: var(--azul); word-break: break-all; line-height: 1.6;
            padding: 0.75rem; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;
        }
        .btn-copiar {
            display: block; width: 100%; margin-top: 1rem; padding: 0.85rem;
            background: var(--azul); color: white; border: none; border-radius: 8px;
            font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: background 0.2s;
        }
        .btn-copiar:active { background: var(--azul-claro); }
        .btn-copiar.copiado { background: var(--verde); }
        .info-grid {
            display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem;
            padding: 0 1.25rem 1.25rem;
        }
        .info-item { padding: 0.6rem; background: #f8fafc; border-radius: 6px; }
        .info-item .label {
            font-size: 0.65rem; text-transform: uppercase;
            letter-spacing: 0.3px; color: var(--cinza); font-weight: 600;
        }
        .info-item .value { font-size: 0.85rem; font-weight: 600; margin-top: 0.15rem; }
        .erro-msg { padding: 1.25rem; font-size: 0.9rem; color: #991b1b; }
        .historico { margin-top: 2rem; }
        .historico h3 {
            font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px;
            color: var(--cinza); font-weight: 600; margin-bottom: 0.75rem;
        }
        .hist-item {
            display: flex; justify-content: space-between; align-items: center;
            padding: 0.75rem 1rem; background: white; border-radius: 8px;
            margin-bottom: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); cursor: pointer;
        }
        .hist-item:active { background: #f8fafc; }
        .hist-chave {
            font-family: 'Courier New', monospace; font-size: 0.75rem;
            color: var(--azul); font-weight: 600;
        }
        .hist-hora { font-size: 0.7rem; color: var(--cinza); }
        footer { text-align: center; padding: 1rem; font-size: 0.7rem; color: var(--cinza); }
    </style>
</head>
<body>
<header>
    <h1>LUVI LOG</h1>
    <p>Extrator de Chave de Acesso NF-e</p>
</header>
<main>
    <div class="upload-area" id="uploadArea">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 0 1 5.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 0 0-1.134-.175 2.31 2.31 0 0 1-1.64-1.055l-.822-1.316a2.192 2.192 0 0 0-1.736-1.039 48.774 48.774 0 0 0-5.232 0 2.192 2.192 0 0 0-1.736 1.039l-.821 1.316Z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0Z" />
        </svg>
        <h2>Envie a foto do DANFE</h2>
        <p>Arraste a imagem aqui ou toque para selecionar</p>
        <button class="btn-camera" onclick="document.getElementById('inputFoto').click()">Tirar Foto / Escolher Arquivo</button>
    </div>
    <input type="file" id="inputFoto" accept="image/*" capture="environment">
    <div class="preview" id="preview">
        <img id="previewImg" src="" alt="Preview">
        <div class="preview-bar">
            <span id="previewNome">foto.jpg</span>
            <button class="btn-trocar" onclick="trocarFoto()">Trocar foto</button>
        </div>
    </div>
    <div class="loading" id="loading">
        <div class="spinner"></div>
        <p>Lendo a chave de acesso...</p>
    </div>
    <div class="resultado" id="resultado"></div>
    <div class="historico" id="historico" style="display:none">
        <h3>Chaves extraidas nesta sessao</h3>
        <div id="historicoLista"></div>
    </div>
</main>
<footer>LUVI LOG Transportes</footer>
<script>
    const uploadArea = document.getElementById('uploadArea');
    const inputFoto = document.getElementById('inputFoto');
    const preview = document.getElementById('preview');
    const previewImg = document.getElementById('previewImg');
    const previewNome = document.getElementById('previewNome');
    const loading = document.getElementById('loading');
    const resultado = document.getElementById('resultado');
    const historico = document.getElementById('historico');
    const historicoLista = document.getElementById('historicoLista');
    let arquivoAtual = null;
    const chavesExtraidas = [];

    uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); uploadArea.classList.add('dragover'); });
    uploadArea.addEventListener('dragleave', () => { uploadArea.classList.remove('dragover'); });
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault(); uploadArea.classList.remove('dragover');
        if (e.dataTransfer.files.length) processarArquivo(e.dataTransfer.files[0]);
    });
    inputFoto.addEventListener('change', (e) => { if (e.target.files.length) processarArquivo(e.target.files[0]); });

    function processarArquivo(arquivo) {
        if (!arquivo.type.startsWith('image/')) { alert('Por favor, envie uma imagem.'); return; }
        arquivoAtual = arquivo;
        previewNome.textContent = arquivo.name;
        const reader = new FileReader();
        reader.onload = (e) => {
            previewImg.src = e.target.result;
            preview.style.display = 'block';
            uploadArea.style.display = 'none';
            resultado.style.display = 'none';
            enviarFoto(arquivo);
        };
        reader.readAsDataURL(arquivo);
    }

    async function enviarFoto(arquivo) {
        loading.style.display = 'block';
        resultado.style.display = 'none';
        const formData = new FormData();
        formData.append('foto', arquivo);
        try {
            const resp = await fetch('/extrair', { method: 'POST', body: formData });
            const data = await resp.json();
            mostrarResultado(data);
        } catch (err) {
            mostrarResultado({ sucesso: false, erro: 'Erro de conexao. Verifique sua internet.' });
        }
        loading.style.display = 'none';
    }

    function mostrarResultado(data) {
        resultado.style.display = 'block';
        if (data.sucesso) {
            let infoHTML = '';
            if (data.info) {
                infoHTML = '<div class="info-grid">' +
                    '<div class="info-item"><div class="label">CNPJ Emitente</div><div class="value">' + data.info.cnpj + '</div></div>' +
                    '<div class="info-item"><div class="label">Numero NF</div><div class="value">' + data.info.numero_nf + '</div></div>' +
                    '<div class="info-item"><div class="label">Modelo / Serie</div><div class="value">' + data.info.modelo + ' / ' + data.info.serie + '</div></div>' +
                    '<div class="info-item"><div class="label">Emissao</div><div class="value">' + data.info.ano_mes + '</div></div>' +
                    '</div>';
            }
            const avisoHTML = data.aviso
                ? '<span class="badge aviso">Conferir</span><span>' + data.aviso + '</span>'
                : '<span class="badge ok">Valida</span><span>Chave verificada com sucesso</span>';
            resultado.innerHTML = '<div class="card"><div class="card-header sucesso">' + avisoHTML +
                '</div><div class="chave-box"><div class="chave-label">Chave de Acesso</div>' +
                '<div class="chave-valor" id="chaveTexto">' + data.chave_formatada + '</div>' +
                '<button class="btn-copiar" id="btnCopiar" onclick="copiarChave(\'' + data.chave + '\')">Copiar chave (44 digitos)</button>' +
                '</div>' + infoHTML + '</div>';
            chavesExtraidas.unshift({
                chave: data.chave, formatada: data.chave_formatada,
                hora: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
                nf: data.info ? data.info.numero_nf : '?',
            });
            atualizarHistorico();
        } else {
            resultado.innerHTML = '<div class="card"><div class="card-header erro">' +
                '<span class="badge falha">Erro</span><span>Nao foi possivel extrair</span></div>' +
                '<div class="erro-msg">' + data.erro + '</div></div>';
        }
    }

    async function copiarChave(chave) {
        try {
            await navigator.clipboard.writeText(chave);
            const btn = document.getElementById('btnCopiar');
            btn.textContent = 'Copiado!';
            btn.classList.add('copiado');
            setTimeout(() => { btn.textContent = 'Copiar chave (44 digitos)'; btn.classList.remove('copiado'); }, 2000);
        } catch {
            const ta = document.createElement('textarea');
            ta.value = chave; document.body.appendChild(ta); ta.select();
            document.execCommand('copy'); document.body.removeChild(ta);
        }
    }

    function trocarFoto() {
        preview.style.display = 'none'; uploadArea.style.display = 'block';
        resultado.style.display = 'none'; inputFoto.value = ''; arquivoAtual = null;
    }

    function atualizarHistorico() {
        if (chavesExtraidas.length === 0) return;
        historico.style.display = 'block';
        historicoLista.innerHTML = chavesExtraidas.map(item =>
            '<div class="hist-item" onclick="copiarChave(\'' + item.chave + '\')">' +
            '<div><div class="hist-chave">' + item.chave.substring(0, 20) + '...</div>' +
            '<div class="hist-hora">NF ' + item.nf + ' - ' + item.hora + '</div></div>' +
            '<span style="font-size:0.75rem;color:#9ca3af">copiar</span></div>'
        ).join('');
    }
</script>
</body>
</html>"""


# ── Rotas ────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def pagina_inicial():
    return PAGINA_HTML


@app.post("/extrair")
async def extrair_chave(foto: UploadFile = File(...)):
    """Recebe a foto e retorna a chave de acesso extraída."""
    try:
        client = get_gemini_client()
    except RuntimeError as e:
        return {"sucesso": False, "erro": str(e)}

    conteudo = await foto.read()
    mime = foto.content_type or "image/jpeg"

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=conteudo, mime_type=mime),
                PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=300,
            ),
        )

        texto = response.text.strip()
        texto = re.sub(r"```json\s*", "", texto)
        texto = re.sub(r"```\s*$", "", texto).strip()
        resultado = json.loads(texto)

    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao processar: {str(e)}"}

    if not resultado.get("encontrou") or not resultado.get("chave_acesso"):
        return {"sucesso": False, "erro": "Nao foi possivel encontrar a chave na imagem. Tente com uma foto mais nitida."}

    chave = re.sub(r"\D", "", resultado["chave_acesso"])

    if len(chave) != 44:
        return {"sucesso": False, "erro": f"Chave extraida tem {len(chave)} digitos (esperado: 44). Tente novamente."}

    dv_valido = validar_chave(chave)

    return {
        "sucesso": True,
        "chave": chave,
        "chave_formatada": formatar_chave(chave),
        "dv_valido": dv_valido,
        "confianca": resultado.get("confianca", "?"),
        "info": decodificar_chave(chave) if dv_valido else None,
        "aviso": None if dv_valido else "Digito verificador invalido. Confira manualmente.",
    }


# ── Inicialização ────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
