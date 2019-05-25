# GitStars

This service provides a limited subset of the Github API geared towards simple front end development.

Using the Github API directly is attractive but problematic when it comes to front end development, especially for simple applications like badges. Without authentication the Github API is limited to only sixty requests an hour, and the responses themselves are rather massive.

This API is geared towards front end development and provides a variety of benefits-

* Higher Ratelimit since the service authenticates with Github,
* Smaller Responses as the service strips out data that can be easily generated,
* Faster Responses due to caching,
* High Resilience, as it will return cached results when issues occur,
* Easy Migration since the service mirrors the Github API endpoints and responses.

There are some limitations though-

* Only Repository and User endpoints are supported.
* Only public repositories are accessible.
* Each object is restricted to a subset of what the Github API provides.
* Everything is read only.


## API Documentation

All of these documents are hosted alongside the API and get updated directly from it.

* [Redoc](https://stars.gitconsensus.com/redoc): This is the best place to review the API itself.
* [Swagger](https://stars.gitconsensus.com/docs): While not as pretty, the built in API client allows you to test the API directly.
* [OpenAPI (json)](https://stars.gitconsensus.com/openapi.json): This is the OpenAPI specification for this API.


## Quick Examples

### Repositories

Repositories can be accessed with the URL pattern `https://stars.gitconsensus.com/repos/{owner}/{repo}`.

> https://stars.gitconsensus.com/repos/ScreepsQuorum/screeps-quorum

```json
{
   "age":0,
   "owner":{
      "login":"ScreepsQuorum"
   },
   "topics":[
      "screeps",
      "gitconsensus"
   ],
   "name":"screeps-quorum",
   "fork":false,
   "description":"Screeps Self Managing and Playing Codebase",
   "homepage":"http:\/\/quorum.tedivm.com\/",
   "html_url":"https:\/\/github.com\/ScreepsQuorum\/screeps-quorum",
   "language":"JavaScript",
   "forks_count":37,
   "open_issues_count":27,
   "stargazers_count":74,
   "subscribers_count":10,
   "archived":false,
   "status":"ok"
}
```

### Users

Users can be accessed with the URL pattern `https://stars.gitconsensus.com/users/{user}`.

> https://stars.gitconsensus.com/users/tedivm

```json
{
   "age":0,
   "login":"tedivm",
   "name":"Robert Hafner",
   "bio":"Lots of personal projects as well as @gitconsensus, @tedious, @LeagueOfAutomatedNations, and @screepers.",
   "blog":"http:\/\/www.tedivm.com",
   "company":null,
   "followers":159,
   "following":106,
   "html_url":"https:\/\/github.com\/tedivm",
   "type":"User",
   "public_repos":115,
   "public_gists":19,
   "status":"ok"
}
```


## Applications Using Gitstars

### [GitButtons](https://gitbuttons.tedivm.com/)

This is a fork of the excellent [buttons.github.io](https://buttons.github.io/), with the only difference between the original being that it uses this API. You can see it in action on [my portfolio page](https://projects.tedivm.com/), where you can refresh repeatedly without the star counts disappearing (as they would with the original Github API due to ratelimiting).
