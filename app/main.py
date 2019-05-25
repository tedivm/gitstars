from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, UrlStr
from typing import List
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import UJSONResponse, RedirectResponse
from datetime import datetime, timedelta
import aiosqlite
import os
import ujson
from github3.exceptions import NotFoundError


import logging
logger = logging.getLogger("uvicorn")



app = FastAPI(
    title='Git Stars',
    description='Extremely Fast Follow Stats for Github Repositories'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

repository_keys = [
    'name',
    'fork',
    'description',
    'homepage',
    'language',
    'forks_count',
    'open_issues_count',
    'stargazers_count',
    'subscribers_count',
    'topics',
    'archived',
]

@app.get("/", include_in_schema=False)
async def redirect():
    return RedirectResponse(url='/redoc')


class BaseResultModel(BaseModel):
    status: str

class ErrorResponse(BaseModel):
    details: str

class RepositoryOwner(BaseModel):
    login: str

class RepositoryResponse(BaseResultModel):
    name: str
    owner: RepositoryOwner
    description: str = None
    homepage: UrlStr = None
    language: str = None
    forks_count: int
    open_issues_count: int
    stargazers_count: int
    subscribers_count: int
    topics: List[str] = []
    archived: bool = False
    fork: bool = False
    age: int

# Should match the scalars above.
repository_keys = [
    'name',
    'fork',
    'description',
    'homepage',
    'language',
    'forks_count',
    'open_issues_count',
    'stargazers_count',
    'subscribers_count',
    'topics',
    'archived',
]


class RequestLimits(BaseModel):
    limit: int
    remaining: int
    reset: int


@app.get('/repos/{owner}/{repository}',
    response_class=UJSONResponse,
    response_model=RepositoryResponse,
    responses={
        302: {"description": "Repository Moved"},
        404: {"description": "Repository Not Found"},
    })
async def repository_info(owner: str, repository: str):
    details = await get_repository_info(owner, repository)
    if not details:
        raise HTTPException(status_code=404, detail="Unable to find repository")

    if owner != details['owner']['login'] or repository != details['name']:
        return RedirectResponse(url='/repos/%s/%s' % (details['owner']['login'], details['name']))

    details['status'] = 'ok'
    expires_at = datetime.utcnow() + timedelta(minutes=os.environ.get('RATELIMIT_PRESERVE', 70))
    headers = {
        'Cache-Control': "public, max-stale=%s" % (60*60*24*30,),
        'Expires': expires_at.strftime('%a, %d %b %Y %H:%M:%S GMT')
    }
    return UJSONResponse(content=details, headers=headers)


@app.get('/ping', response_class=UJSONResponse, response_model=BaseResultModel)
async def health_check():
    return {'status': 'ok'}


@app.get('/ratelimit', response_class=UJSONResponse, response_model=RequestLimits)
async def ratelimit():
    ratelimits = await get_ratelimits()
    ratelimits['status'] = 'ok'
    return ratelimits


async def get_repository_info(owner, repository):
    saved_details = await get_saved_repository_info_from_sqlite(owner, repository)
    if not saved_details:
        github_details = await get_repository_info_from_github(owner, repository)
        await save_repository_info_into_sqlite(owner, repository, github_details)
        return github_details


    if saved_details['age'] < int(os.environ.get('CACHE_TTL', 60)):
        return saved_details


    # If the ratelimit is running out save API calls for new entries.
    ratelimits = await get_ratelimits()
    requests_remaining_percent = int(ratelimits['remaining']/ratelimits['limit']*100)
    if requests_remaining_percent < int(os.environ.get('RATELIMIT_PRESERVE', 10)):
        return saved_details

    github_details = await get_repository_info_from_github(owner, repository)
    await save_repository_info_into_sqlite(owner, repository, github_details)
    return github_details


async def get_repository_info_from_github(owner, repository):
    ratelimits = await get_ratelimits()
    print(ratelimit)
    if ratelimits['remaining'] < 10:
        return False

    try:
        gh = get_github_client()
        repo = gh.repository(owner, repository)
    except NotFoundError:
        return False

    if repo.private:
        return False

    repo_details = {
        'age': 0
    }
    for key in repository_keys:
        if hasattr(repo, key):
            repo_details[key] = getattr(repo, key)


    repo_details['owner'] = {
        'login': repo.owner.login
    }

    '''
    repo_details = {
        'forks': repo.forks_count,
        'issues': repo.open_issues_count,
        'stargazers': repo.stargazers_count,
        'watchers': repo.subscribers_count,
        'age': 0
    }
    '''

    return repo_details


async def save_repository_info_into_sqlite(owner, repository, details):
    await create_database()
    async with aiosqlite.connect(get_sqlite_path()) as db:
        insert_sql = 'REPLACE INTO repositories (owner, repository, update_time, details_json) VALUES(?, ?, ?, ?)'
        await db.execute(insert_sql, (owner, repository, int(datetime.timestamp(datetime.now())), ujson.dumps(details)))
        await db.commit()


async def get_saved_repository_info_from_sqlite(owner, repository):
    await create_database()
    async with aiosqlite.connect(get_sqlite_path()) as db:
        select_sql = 'SELECT update_time, details_json FROM repositories WHERE owner = ? AND repository = ?'
        cursor = await db.execute(select_sql, (owner, repository))
        row = await cursor.fetchone()
        if not row:
            return False
        age_in_seconds = int(datetime.timestamp(datetime.now())) - int(row[0])
        details = ujson.loads(row[1])
        if details:
            details['age'] = int((int(datetime.timestamp(datetime.now())) - int(row[0]))/60)
        return details


async def create_database():
    async with aiosqlite.connect(get_sqlite_path()) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS repositories (
                                 owner text,
                                 repository text,
                                 update_time int,
                                 details_json text,
                                 PRIMARY KEY (owner, repository)
                             )
                            ''')
        await db.commit()


async def get_ratelimits():
    gh = get_github_client()
    return gh._get('https://api.github.com/rate_limit').json()['resources']['core']


def get_github_client():
    from github3 import login
    if 'GITHUB_TOKEN' in os.environ:
        return login(token=os.environ['GITHUB_TOKEN'])
    return login()


def get_sqlite_path():
    if 'SQLITE_PATH' in os.environ:
        return os.path.expanduser(os.environ['SQLITE_PATH'])
    return os.path.expanduser('~/gitstar_cache.sqlite3')
