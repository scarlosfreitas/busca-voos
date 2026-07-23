# Plugins skills e mcps que poderão ser instalados no container de desenvolvimento
# o usuario deverá decidir quais serão necessários, e instalar manualmente, para não poluir o container com plugins desnecessários.

# Agent browser
# sudo npm install -g --allow-scripts=agent-browser agent-browser
# agent-browser install --with-deps
# npx skills add vercel-labs/agent-browser

# Context7
claude plugin install context7@claude-plugins-official --scope user

# context-mode
claude plugin marketplace add mksglu/context-mode
claude plugin install context-mode@context-mode --scope user

# Playwright CLI (browsers + testes; sem MCP)
npm install -g @playwright/cli@latest
playwright install --with-deps

# Interface Design Skill 
npx skills add https://github.com/dammyjay93/interface-design --skill interface-design

# Napkin
git clone https://github.com/blader/napkin.git ~/.claude/skills/napkin