"""Synthetic evidence for exercising plumbing, never publishable research."""
from copy import deepcopy


def research(window):
    return {'fixture_only':True,'news':[{
        'id':f'n{i}','event_date':window['start'],'title':f'Синтетическая новость {i} - не публиковать',
        'claim':f'Тестовый факт {i}, не описание реального события.',
        'primary_url':f'https://yandex.ru/fixture-{i}', 'confirmation_url':f'https://yandex.ru/fixture-{i}',
        'quote':f'Синтетический факт номер {i} используется только для проверки системы.',
        'date_quote':f'Дата синтетического события: {window["start"]}.',
        'why_it_matters':'Только проверка передачи данных между этапами.'} for i in (1,2,3)]}


def source(url,allowed):
    number=url.rsplit('-',1)[-1]
    return f'<html><p>Синтетический факт номер {number} используется только для проверки системы.</p><p>Дата синтетического события: 2026-10-26.</p><p>Дата синтетического события: 2026-11-02.</p></html>'


def article():
    return {'title':'Синтетический дайджест VericoMedia - не публиковать',
      'seo_title':'Техническая проверка редакционной цепочки VericoMedia',
      'description':'Синтетические данные для проверки вёрстки, оглавления и передачи материалов. Не новостная публикация.',
      'subtitle':'Это тест цепочки, а не реальные новости маркетинга.',
      'lead':'Ни один тестовый факт ниже не описывает событие. Проверяем структуру и сохранение промежуточных файлов.',
      'sections':[{'id':f'news-{i}','heading':f'Проверка редакционного раздела {i}',
                   'source_ids':[f'n{i}'], 'paragraphs':['**Тестовая формулировка.** Система сохраняет источник и дату отдельно от редакционного комментария.','Эта часть проверяет читаемость текста, переносы строк и интервалы. Никаких выдуманных результатов клиентов здесь нет.'],
                   'quote':'','bullets':['Проверить источник.','Сохранить промежуточный результат.'] if i==2 else []} for i in (1,2,3)]}


class FixtureModel:
    def __init__(self,window):self.window=window;self.calls=0;self.usage=[]
    def json(self,instruction,payload,search=False):
        self.calls+=1
        if self.calls==1:return research(self.window)
        if self.calls==2:return article()
        if self.calls==3:
            obj=deepcopy(payload['draft']);obj['sections'][0]['paragraphs'][0]='**Отредактированная тестовая формулировка.** Источник и дата хранятся отдельно от авторского комментария.'
            obj['editing_notes']=['Сокращена первая формулировка; синтетические факты не добавлялись.']
            return obj
        return {'passed':True,'problems':[],'checked_source_ids':['n1','n2','n3'],'event_dates_verified':True,'fixture_only':True}
    def cost(self):return 0
