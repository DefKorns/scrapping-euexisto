# Blogger → Static Site Backup

---

Este projeto nasceu de uma premissa simples: não deixar que as palavras de um amigo se percam.

O Júlio Ávila escreveu este blog durante anos — pensamentos, observações, pedaços de vida. Já não está entre nós, mas o que escreveu continua a ter valor, e merece continuar acessível, fora das mãos de plataformas que um dia podem simplesmente desligar os servidores.

Este script existe para isso: copiar tudo — posts, imagens, comentários de quem o leu e lhe respondeu — para um site simples e estático, que pode viver onde quisermos, para sempre.

---

Script Python que faz o backup de um blog [Blogger](https://www.blogger.com/) para um site estático em HTML, incluindo posts, imagens e comentários nativos.

## Funcionalidades

- Lê todos os posts via feed Atom do Blogger (`/feeds/posts/default`)
- Gera uma página individual por post em `posts/ano/mes/nome.html`
- Gera uma página `index.html` com listagem de todos os posts, com paginação "Carregar mais"
- Descarrega imagens referenciadas nos posts e guarda-as localmente em `images/`
- Faz lazy-loading automático das imagens (`loading="lazy"`)
- Faz scraping dos **comentários nativos do Blogger** (via feed Atom de comentários) e mostra-os em cada post
- Cache local de comentários (`comments_cache.json`) — não volta a pedir comentários de posts já processados
- Cache de imagens que falharam (`failed_images.txt`) — não tenta repetidamente imagens inacessíveis
- CSS partilhado num único ficheiro `style.css`

## Requisitos

- Python 3.10+
- [`requests`](https://pypi.org/project/requests/)

```bash
pip install requests
```

## Uso

```bash
python backup_blog.py -url https://nomedoblog.blogspot.com
```

### Opções

| Argumento | Descrição | Default |
|---|---|---|
| `-url`, `--url` | URL do blog Blogger (obrigatório) | — |
| `--initial-visible` | Nº de posts visíveis inicialmente no index | `15` |
| `--load-more-step` | Nº de posts a carregar por clique em "Carregar mais" | `15` |

## Output

O site gerado fica em `backup/site/`:

```
backup/site/
├── index.html
├── style.css
├── comments_cache.json
├── failed_images.txt
├── images/
│   └── <hash>.jpg
└── posts/
    └── 2018/
        └── 10/
            └── titulo-do-post.html
```

## Notas

- Re-executar o script é seguro: imagens e comentários já descarregados não são pedidos de novo.
- Para forçar a actualização de comentários de um post específico, remove a entrada correspondente de `comments_cache.json`.
- Se uma imagem falhar repetidamente (ex: já não existe online), o URL é guardado em `failed_images.txt` e ignorado em execuções futuras. Para tentar de novo, remove a linha correspondente.
