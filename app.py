"""
LUVI LOG - Extrator de Chave de Acesso NF-e
"""

import os
import re
import json
import time

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from google import genai
from google.genai import types

app = FastAPI(title="LUVI LOG")

gemini_client = None


def get_gemini_client():
    global gemini_client
    if gemini_client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY nao configurada")
        gemini_client = genai.Client(api_key=api_key)
    return gemini_client


PROMPT = """Analise esta imagem de um DANFE ou Nota Fiscal e extraia a CHAVE DE ACESSO de 44 digitos numericos.
A chave geralmente aparece abaixo do codigo de barras ou no topo do documento.
Responda APENAS com os 44 digitos da chave, sem espacos, sem texto extra, sem JSON.
Se nao encontrar, responda apenas: NAO_ENCONTRADA"""

MODELOS = ["gemini-2.5-flash", "gemini-2.0-flash"]


def extrair_chave_do_texto(texto):
    """Tenta extrair uma sequencia de 44 digitos de qualquer texto."""
    # Remove tudo que nao e digito e tenta achar 44 consecutivos
    somente_digitos = re.sub(r"\D", "", texto)

    # Procura sequencia de exatamente 44 digitos
    match = re.search(r"\d{44}", somente_digitos)
    if match:
        return match.group(0)

    # Se o texto todo limpo tem 44 digitos
    if len(somente_digitos) == 44:
        return somente_digitos

    return None


def chamar_gemini(client, conteudo, mime):
    """Tenta ate 3 vezes com modelo reserva."""
    ultimo_erro = None
    for modelo in MODELOS:
        for tentativa in range(3):
            try:
                response = client.models.generate_content(
                    model=modelo,
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

                # Se respondeu que nao encontrou
                if "NAO_ENCONTRADA" in texto.upper() or "NAO ENCONTR" in texto.upper():
                    return {"encontrou": False, "chave_acesso": None}

                # Tenta extrair a chave do texto (funciona com JSON, texto puro, etc)
                chave = extrair_chave_do_texto(texto)
                if chave:
                    return {"encontrou": True, "chave_acesso": chave, "confianca": "alta"}

                # Se nao encontrou 44 digitos na resposta
                return {"encontrou": False, "chave_acesso": None}

            except Exception as e:
                ultimo_erro = str(e)
                if "503" in ultimo_erro or "UNAVAILABLE" in ultimo_erro or "overloaded" in ultimo_erro.lower():
                    time.sleep(2 * (tentativa + 1))
                    continue
                elif tentativa < 2:
                    time.sleep(1)
                    continue
                else:
                    break

    raise RuntimeError("Servidores indisponiveis. Tente novamente em 1 minuto. (" + str(ultimo_erro)[:100] + ")")


def validar_chave(chave):
    if not chave or len(chave) != 44 or not chave.isdigit():
        return False
    ufs = {"11","12","13","14","15","16","17","21","22","23","24","25","26","27","28","29","31","32","33","35","41","42","43","50","51","52","53"}
    if chave[:2] not in ufs:
        return False
    if chave[20:22] not in ("55", "65", "57"):
        return False
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(chave[:43])))
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return int(chave[43]) == dv


def decodificar_chave(chave):
    modelos = {"55": "NF-e", "65": "NFC-e", "57": "CT-e"}
    return {
        "uf": chave[0:2],
        "ano_mes": "20" + chave[2:4] + "/" + chave[4:6],
        "cnpj": chave[6:8] + "." + chave[8:11] + "." + chave[11:14] + "/" + chave[14:18] + "-" + chave[18:20],
        "modelo": modelos.get(chave[20:22], chave[20:22]),
        "serie": str(int(chave[22:25])),
        "numero_nf": str(int(chave[25:34])),
    }


def formatar_chave(chave):
    return " ".join(chave[i:i+4] for i in range(0, 44, 4))


PAGINA = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LUVI LOG - Extrator NF-e</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#faf8f3;color:#1f2937;min-height:100vh;display:flex;flex-direction:column}
header{background:#1a3a6b;color:#fff;padding:1.2rem;text-align:center}
header h1{font-size:1.3rem}
header p{font-size:0.8rem;opacity:0.7;margin-top:0.2rem}
main{flex:1;padding:1.5rem;max-width:540px;margin:0 auto;width:100%}
#zona{border:2px dashed #d1d5db;border-radius:12px;padding:2.5rem 1.5rem;text-align:center;background:#fff}
#zona h2{font-size:1rem;font-weight:600;margin-bottom:0.3rem}
#zona p{font-size:0.8rem;color:#6b7280}
#botao{margin-top:1rem;padding:0.7rem 1.5rem;background:#1a3a6b;color:#fff;border:none;border-radius:8px;font-size:0.9rem;font-weight:600;cursor:pointer}
#arq{display:none}
#prev{display:none;margin-top:1.2rem;border-radius:12px;overflow:hidden;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,0.08)}
#prev img{width:100%;max-height:280px;object-fit:cover}
#prevbar{display:flex;justify-content:space-between;align-items:center;padding:0.7rem 1rem}
#prevbar span{font-size:0.8rem;color:#6b7280}
#trocar{font-size:0.8rem;color:#2c5aa0;background:none;border:none;cursor:pointer;font-weight:600}
#load{display:none;text-align:center;margin-top:2rem}
#load .sp{width:36px;height:36px;border:3px solid #e5e7eb;border-top-color:#1a3a6b;border-radius:50%;animation:girar 0.7s linear infinite;margin:0 auto 0.7rem}
@keyframes girar{to{transform:rotate(360deg)}}
#load p{font-size:0.85rem;color:#6b7280}
#res{display:none;margin-top:1.5rem}
.card{background:#fff;border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,0.08);overflow:hidden}
.hok{padding:1rem;display:flex;align-items:center;gap:0.6rem;background:#f0fdf4;border-bottom:1px solid #bbf7d0}
.herr{padding:1rem;display:flex;align-items:center;gap:0.6rem;background:#fef2f2;border-bottom:1px solid #fecaca}
.bok{font-size:0.7rem;font-weight:600;padding:0.2rem 0.6rem;border-radius:20px;background:#dcfce7;color:#166534}
.berr{font-size:0.7rem;font-weight:600;padding:0.2rem 0.6rem;border-radius:20px;background:#fee2e2;color:#991b1b}
.cbox{padding:1.2rem}
.cbox label{font-size:0.7rem;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;font-weight:600;display:block;margin-bottom:0.5rem}
.cval{font-family:monospace;font-size:0.95rem;font-weight:600;color:#1a3a6b;word-break:break-all;line-height:1.6;padding:0.7rem;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0}
#copiar{display:block;width:100%;margin-top:1rem;padding:0.85rem;background:#1a3a6b;color:#fff;border:none;border-radius:8px;font-size:0.95rem;font-weight:600;cursor:pointer}
.igrid{display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;padding:0 1.2rem 1.2rem}
.ii{padding:0.6rem;background:#f8fafc;border-radius:6px}
.ii small{font-size:0.65rem;text-transform:uppercase;color:#6b7280;font-weight:600}
.ii div{font-size:0.85rem;font-weight:600;margin-top:0.1rem}
.errmsg{padding:1.2rem;font-size:0.9rem;color:#991b1b}
#retry{display:block;width:100%;margin-top:0.8rem;padding:0.75rem;background:#1a3a6b;color:#fff;border:none;border-radius:8px;font-size:0.9rem;font-weight:600;cursor:pointer}
footer{text-align:center;padding:1rem;font-size:0.7rem;color:#6b7280}
</style>
</head>
<body>
<header><h1>LUVI LOG</h1><p>Extrator de Chave de Acesso NF-e</p></header>
<main>
<div id="zona">
<h2>Envie a foto do DANFE</h2>
<p>Toque para selecionar ou tirar foto</p>
<button id="botao" type="button">Tirar Foto / Escolher Arquivo</button>
</div>
<input type="file" id="arq" accept="image/*">
<div id="prev"><img id="previmg" src="" alt=""><div id="prevbar"><span id="nomeArq"></span><button id="trocar" type="button">Trocar foto</button></div></div>
<div id="load"><div class="sp"></div><p>Lendo a chave de acesso...</p></div>
<div id="res"></div>
</main>
<footer>LUVI LOG Transportes</footer>
<script>
var chaveAtual = "";
var arquivoAtual = null;

document.getElementById("botao").onclick = function() {
    document.getElementById("arq").click();
};

document.getElementById("zona").onclick = function() {
    document.getElementById("arq").click();
};

document.getElementById("trocar").onclick = function() {
    document.getElementById("prev").style.display = "none";
    document.getElementById("zona").style.display = "block";
    document.getElementById("res").style.display = "none";
    document.getElementById("arq").value = "";
    arquivoAtual = null;
};

document.getElementById("arq").onchange = function() {
    var file = this.files[0];
    if (!file) return;
    arquivoAtual = file;

    document.getElementById("nomeArq").textContent = file.name;

    var reader = new FileReader();
    reader.onload = function(e) {
        document.getElementById("previmg").src = e.target.result;
        document.getElementById("prev").style.display = "block";
        document.getElementById("zona").style.display = "none";
        document.getElementById("res").style.display = "none";
        enviar(file);
    };
    reader.readAsDataURL(file);
};

function enviar(file) {
    document.getElementById("load").style.display = "block";
    document.getElementById("res").style.display = "none";

    var fd = new FormData();
    fd.append("foto", file);

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/extrair");
    xhr.onload = function() {
        document.getElementById("load").style.display = "none";
        try {
            var data = JSON.parse(xhr.responseText);
            mostrar(data);
        } catch(e) {
            mostrar({sucesso: false, erro: "Erro ao processar resposta do servidor."});
        }
    };
    xhr.onerror = function() {
        document.getElementById("load").style.display = "none";
        mostrar({sucesso: false, erro: "Erro de conexao. Verifique sua internet."});
    };
    xhr.send(fd);
}

function tentarNovamente() {
    if (arquivoAtual) {
        enviar(arquivoAtual);
    }
}

function mostrar(data) {
    var res = document.getElementById("res");
    res.style.display = "block";

    if (data.sucesso) {
        chaveAtual = data.chave;
        var info = "";
        if (data.info) {
            info = '<div class="igrid">'
                + '<div class="ii"><small>CNPJ Emitente</small><div>' + data.info.cnpj + '</div></div>'
                + '<div class="ii"><small>Numero NF</small><div>' + data.info.numero_nf + '</div></div>'
                + '<div class="ii"><small>Modelo / Serie</small><div>' + data.info.modelo + ' / ' + data.info.serie + '</div></div>'
                + '<div class="ii"><small>Emissao</small><div>' + data.info.ano_mes + '</div></div>'
                + '</div>';
        }

        var hdr = data.aviso
            ? '<div class="herr"><span class="berr">Conferir</span><span>' + data.aviso + '</span></div>'
            : '<div class="hok"><span class="bok">Valida</span><span>Chave verificada com sucesso</span></div>';

        res.innerHTML = '<div class="card">' + hdr
            + '<div class="cbox"><label>Chave de Acesso</label>'
            + '<div class="cval">' + data.chave_formatada + '</div>'
            + '<button id="copiar" type="button" onclick="copiarChave()">Copiar chave (44 digitos)</button>'
            + '</div>' + info + '</div>';
    } else {
        res.innerHTML = '<div class="card">'
            + '<div class="herr"><span class="berr">Erro</span><span>Nao foi possivel extrair</span></div>'
            + '<div class="errmsg">' + data.erro + '</div>'
            + '<div style="padding:0 1.2rem 1.2rem"><button id="retry" type="button" onclick="tentarNovamente()">Tentar novamente</button></div>'
            + '</div>';
    }
}

function copiarChave() {
    var btn = document.getElementById("copiar");
    if (navigator.clipboard) {
        navigator.clipboard.writeText(chaveAtual).then(function() {
            btn.textContent = "Copiado!";
            btn.style.background = "#16a34a";
            setTimeout(function() { btn.textContent = "Copiar chave (44 digitos)"; btn.style.background = "#1a3a6b"; }, 2000);
        });
    } else {
        var ta = document.createElement("textarea");
        ta.value = chaveAtual;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        btn.textContent = "Copiado!";
        btn.style.background = "#16a34a";
        setTimeout(function() { btn.textContent = "Copiar chave (44 digitos)"; btn.style.background = "#1a3a6b"; }, 2000);
    }
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def pagina_inicial():
    return PAGINA


@app.post("/extrair")
async def extrair_chave(foto: UploadFile = File(...)):
    try:
        client = get_gemini_client()
    except RuntimeError as e:
        return {"sucesso": False, "erro": str(e)}

    conteudo = await foto.read()
    mime = foto.content_type or "image/jpeg"

    try:
        resultado = chamar_gemini(client, conteudo, mime)
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

    if not resultado.get("encontrou") or not resultado.get("chave_acesso"):
        return {"sucesso": False, "erro": "Nao encontrou a chave na imagem. Tente com foto mais nitida."}

    chave = resultado["chave_acesso"]

    if len(chave) != 44:
        return {"sucesso": False, "erro": "Chave tem " + str(len(chave)) + " digitos (esperado: 44)."}

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


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
