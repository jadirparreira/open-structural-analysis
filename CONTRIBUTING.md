# Contribuindo

Obrigado pelo interesse em contribuir com o Open Structural Analysis. Este
projeto usa o fluxo de fork, branch temática e Pull Request do GitHub.

## 1. Criar o fork

Abra o [repositório original](https://github.com/jadirparreira/open-structural-analysis),
clique em **Fork** e crie uma cópia na sua conta ou organização.

## 2. Clonar o seu fork

Clone a sua cópia, e não o repositório original:

```bash
git clone https://github.com/SEU_USUARIO/open-structural-analysis.git
cd open-structural-analysis
```

## 3. Configurar o repositório original

Adicione o repositório original como `upstream`:

```bash
git remote add upstream https://github.com/jadirparreira/open-structural-analysis.git
git remote -v
```

O resultado deve mostrar `origin` apontando para o seu fork e `upstream`
apontando para `jadirparreira/open-structural-analysis`.

## 4. Criar uma branch de trabalho

Não desenvolva diretamente na branch `main`. Atualize-a e crie uma branch
temática:

```bash
git switch main
git pull upstream main
git switch -c feat/nome-da-funcionalidade
```

Para correções, use o prefixo `fix/`, por exemplo:

```bash
git switch -c fix/corrige-falha-no-renderizador
```

## 5. Desenvolver e testar

Instale as dependências de desenvolvimento e execute os testes e o lint:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Antes de comitar, confira os arquivos modificados:

```bash
git status
git diff --check
```

## 6. Criar o commit

Mantenha os commits pequenos e relacionados a uma única alteração:

```bash
git add arquivos-alterados
git commit -m "feat: descreve a alteração"
```

Use a sua própria identidade Git ao contribuir. Para conferir a configuração:

```bash
git config user.name
git config user.email
```

Não inclua segredos, ambientes virtuais, arquivos locais, créditos, trailers
ou metadados referentes a ferramentas externas de assistência, geração ou
automação.

## 7. Enviar a branch para o seu fork

```bash
git push -u origin feat/nome-da-funcionalidade
```

## 8. Abrir o Pull Request

No GitHub, abra um Pull Request do seu fork para o repositório original e
confirme:

- **Base repository:** `jadirparreira/open-structural-analysis`;
- **Base branch:** `main`;
- **Head repository:** o seu fork;
- **Compare branch:** a branch temática criada por você.

Descreva o que foi alterado, por que a alteração é necessária e informe issues
relacionadas, quando houver.

## 9. Manter o fork sincronizado

Para atualizar a branch principal do seu fork:

```bash
git switch main
git fetch upstream
git merge upstream/main
git push origin main
```

Também é possível usar **Sync fork** → **Update branch** na interface do
GitHub.

## Boas práticas

- Mantenha uma funcionalidade ou correção por Pull Request.
- Evite commits grandes e sem relação entre si.
- Não misture alterações de estilo com mudanças funcionais sem necessidade.
- Verifique os resultados dos testes e do lint antes de abrir o Pull Request.
- Acompanhe os checks do GitHub e responda aos comentários da revisão.
