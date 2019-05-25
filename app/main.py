from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, UrlStr
from typing import List
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import UJSONResponse, RedirectResponse
from datetime import datetime, timedelta
import aiosqlite
import os
import ujson
from enum import Enum
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
    html_url: UrlStr
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
    'html_url',
    'language',
    'forks_count',
    'open_issues_count',
    'stargazers_count',
    'subscribers_count',
    'topics',
    'archived',
]


class TypeEnum(str, Enum):
    organization = 'Organization'
    user = 'User'


class UserResponse(BaseResultModel):
    login: str
    type: TypeEnum
    name: str = None
    bio: str = None
    blog: UrlStr = None
    company: str = None
    followers: int = 0
    following: int = 0
    html_url: UrlStr
    public_repos: int = 0

# Should match the values above
user_keys = [
    'login',
    'name',
    'bio',
    'blog',
    'company',
    'followers',
    'following',
    'html_url',
    'type',
    'public_repos',
    'public_gists',
]


class Storage(BaseResultModel):
    repository_count: int = 0
    user_count: int = 0


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
async def repository_info(owner: str, repository: str, background_tasks: BackgroundTasks):
    details = await get_github_info(owner, repository, background_tasks)
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


@app.get('/users/{user}',
    response_class=UJSONResponse,
    response_model=UserResponse,
    responses={
        404: {"description": "User Not Found"},
    })
async def user_info(user: str, background_tasks: BackgroundTasks):
    details = await get_github_info(user, False, background_tasks)
    if not details:
        raise HTTPException(status_code=404, detail="Unable to find user")
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


@app.get('/storage', response_class=UJSONResponse, response_model=Storage)
async def storage():
    await create_database()
    return {
        'status': 'ok',
        'repository_count': await get_stored_repository_count(),
        'user_count': await get_stored_user_count(),
    }


async def get_github_info(owner, repository, background_tasks=False):
    saved_details = await get_saved_github_info_from_sqlite(owner, repository)
    if not saved_details:
        github_details = await get_info_from_github(owner, repository)
        await save_github_info_into_sqlite(owner, repository, github_details)
        return github_details

    if saved_details['age'] < int(os.environ.get('CACHE_SOFT_TTL', 60)):
        return saved_details

    # Between the SOFT_TTL and HARD_TTL apply a random change of regenerating.
    # This distributes misses to smooth out calls to the github api.
    if saved_details['age'] < int(os.environ.get('CACHE_HARD_TTL', 600)):
        if random.random() < float(os.environ.get('CACHE_REGENERATE_CHANCE', 10))/100:
            return saved_details

    # If the ratelimit is running out save API calls for new entries.
    ratelimits = await get_ratelimits()
    requests_remaining_percent = int(ratelimits['remaining']/ratelimits['limit']*100)
    if requests_remaining_percent < int(os.environ.get('RATELIMIT_PRESERVE', 10)):
        return saved_details

    github_details = await get_info_from_github(owner, repository)
    if background_tasks:
        background_tasks.add_task(save_github_info_into_sqlite, repository, github_details)
    else:
        await save_github_info_into_sqlite(owner, repository, github_details)
    return github_details


async def get_info_from_github(owner, repository):
    if repository:
        return await get_repository_info_from_github(owner, repository)
    else:
        return await get_user_info_from_github(owner)


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

    return repo_details


async def get_user_info_from_github(user):
    ratelimits = await get_ratelimits()
    print(ratelimit)
    if ratelimits['remaining'] < 10:
        return False

    try:
        gh = get_github_client()
        user = gh.user(user)
    except NotFoundError:
        return False

    user_details = {
        'age': 0
    }
    for key in user_keys:
        if hasattr(user, key):
            user_details[key] = getattr(user, key)

    user_details['followers'] = user.followers_count
    user_details['following'] = user.following_count

    return user_details


async def save_github_info_into_sqlite(owner, repository, details):
    await create_database()
    async with aiosqlite.connect(get_sqlite_path()) as db:
        if repository:
            insert_sql = 'REPLACE INTO repositories (owner, repository, update_time, details_json) VALUES(?, ?, ?, ?)'
            await db.execute(insert_sql, (owner, repository, int(datetime.timestamp(datetime.now())), ujson.dumps(details)))
        else:
            insert_sql = 'REPLACE INTO users (user, update_time, details_json) VALUES(?, ?, ?)'
            await db.execute(insert_sql, (owner, int(datetime.timestamp(datetime.now())), ujson.dumps(details)))
        await db.commit()


async def get_saved_github_info_from_sqlite(owner, repository):
    await create_database()
    async with aiosqlite.connect(get_sqlite_path()) as db:
        if repository:
            select_sql = 'SELECT update_time, details_json FROM repositories WHERE owner = ? AND repository = ?'
            cursor = await db.execute(select_sql, (owner, repository))
        else:
            select_sql = 'SELECT update_time, details_json FROM users WHERE user = ?'
            cursor = await db.execute(select_sql, (owner,))
        row = await cursor.fetchone()
        if not row:
            return False
        age_in_seconds = int(datetime.timestamp(datetime.now())) - int(row[0])
        details = ujson.loads(row[1])
        if details:
            details['age'] = int((int(datetime.timestamp(datetime.now())) - int(row[0]))/60)
        return details


async def get_stored_repository_count():
    async with aiosqlite.connect(get_sqlite_path()) as db:
        async with db.execute('select (select count() from repositories) as count, * from repositories') as cursor:
            row = await cursor.fetchone()
            if not row:
                return 0
            return row[0]


async def get_stored_user_count():
    async with aiosqlite.connect(get_sqlite_path()) as db:
        async with db.execute('select (select count() from users) as count, * from users') as cursor:
            row = await cursor.fetchone()
            if not row:
                return 0
            return row[0]


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
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
                                 user text,
                                 update_time int,
                                 details_json text,
                                 PRIMARY KEY (user)
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
