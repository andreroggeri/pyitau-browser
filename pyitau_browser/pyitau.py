from datetime import datetime
from typing import TypedDict, List, Optional

from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright, Route


def request_handler(route: Route):
    print(route.request.url)
    route.continue_()


def get_appropriate_date(date: str, invoice_date: str) -> datetime:
    parsed_invoice_date = datetime.strptime(invoice_date, '%d/%m/%y')
    parsed_date = datetime.strptime(date, '%d / %b / %Y')
    
    if (parsed_date - parsed_invoice_date).days > 60:
        return parsed_date - relativedelta(years=1)
    else:
        return parsed_date


class AccountStatementDetail(TypedDict):
    name: Optional[str]
    transaction_type: str


class AccountStatement(TypedDict):
    date: datetime
    description: str
    amount: float
    details: Optional[AccountStatementDetail]


class Itau:
    
    def __init__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=False)
        self.context = self.browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36')
        self.context.tracing.start(screenshots=True, snapshots=True)
        self.page = self.context.new_page()
    
    def login(self, branch, account_no, password):
        self.page.goto('https://www.itau.com.br/')
        
        self.page.get_by_placeholder('agência').type(branch)
        self.page.get_by_placeholder('conta').type(account_no)
        self.page.get_by_role("button", name="Acessar").click()
        
        keypass_container = self.page.wait_for_selector('css=div.teclas.clearfix')
        for digit in password:
            keypass_button = keypass_container.query_selector(f'css=a:has-text("{digit}")')
            keypass_button.click()
        
        self.page.click('id=acessar')
    
    def get_account_statements(self):
        self.page.click('css=a[title="Home"]')
        self.page.click('id=saldo-extrato-card-accordion')
        self.page.click('css=button:has-text("ver extrato")')
        
        self.page.click('id=periodoFiltro')
        self.page.click('css=li:has-text("Últimos 90 dias")')
        
        self.page.wait_for_selector('css=#gridLancamentos-pessoa-fisica tbody tr')
        rows = self.page.query_selector_all(
            'css=#extrato-grid-lancamentos #gridLancamentos-pessoa-fisica tbody tr:not(.linha-tabela-lancamentos-pf-saldo-dia):not(.linha-descricao-mes-ano):not(.linha-descricao-mes-ano)')
        
        parsed: List[AccountStatement] = []
        for row in rows:
            date, description, value, balance, detail = row.query_selector_all('td')
            
            detail_button = detail.query_selector('css=button')
            
            details: AccountStatementDetail = {}
            if detail_button:
                detail_button.click()
                details['name'] = self.page.text_content('css=.identificacao-texto--name')
                details['transaction_type'] = 'pix'
            
            parsed.append({
                'date': datetime.strptime(date.inner_text(), '%d/%m/%Y'),
                'description': description.inner_text(),
                'amount': float(value.inner_text().replace('.', '').replace(',', '.')),
                'details': details
            })
        
        return parsed
    
    def get_credit_card_statements(self):
        def extract_statements_from_tables(tables):
            invoice_date = self.page.text_content('css=.container-lateral .c-category-status__value')
            parsed = []
            for table in tables:
                rows = table.query_selector_all('css=tbody tr')
                aggregated_date = ''
                for row in rows:
                    date, description, value = row.query_selector_all('td')
                    now = datetime.now()
                    aggregated_date = date.inner_text() if date.inner_text() else aggregated_date
                    formatted_date = f'{aggregated_date} / {now.year}'
                    formatted_value = value.inner_text() \
                        .replace('.', '') \
                        .replace(',', '.') \
                        .replace('R$', '') \
                        .replace('US$', '') \
                        .replace('BRL', '')
                    
                    if '\n' in formatted_value:
                        formatted_value = formatted_value.split('\n')[1]
                    
                    parsed.append({
                        'date': get_appropriate_date(formatted_date, invoice_date),
                        'description': description.inner_text(),
                        'amount': float(formatted_value),
                    })
            return parsed
        
        self.page.click('css=a[title="Home"]')
        self.page.click('id=cartao-card-accordion')
        self.page.click('css=a[title="ver fatura cartão"]')
        self.page.wait_for_selector('css=table.fatura__table:not(.fatura__table--detalhes-saldo)')
        
        tables = self.page.query_selector_all('css=table.fatura__table:not(.fatura__table--detalhes-saldo)')
        
        parsed = extract_statements_from_tables(tables)
        # Next month
        next_month = datetime.now() + relativedelta(months=1)
        next_month_label = next_month.strftime('%B').lower()
        self.page.click(f'id=btn-{next_month_label}')
        self.page.wait_for_load_state('networkidle')
        self.page.wait_for_selector('css=table.fatura__table:not(.fatura__table--detalhes-saldo)')
        tables = self.page.query_selector_all('css=table.fatura__table:not(.fatura__table--detalhes-saldo)')
        parsed = parsed + extract_statements_from_tables(tables)
        return parsed
