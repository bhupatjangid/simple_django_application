import re
from functools import wraps

import redis
from django.conf import settings
from django.core.exceptions import EmptyResultSet
from django.db.backends.utils import CursorDebugWrapper
from django.db.models.sql import compiler
from django.db.models.sql.constants import MULTI
from redis import ResponseError
from redisearch import Client, NumericField, TagField, TextField
import json

# CACHE_HOST = "localhost"
# CACHE_PORT = 6379
# CACHE_DB = 0
# CACHE_BLACKLIST = ["django_migration", "auth_", "django_content_"]
# CACHE_INDEX = "testgt"
# CACHE_LOG = False


def create_redisearch_index(index_name):
    r = redis.Redis(
        host='redis',
        port= 6379,
        db=0,
        # username="default",
        # password="redispassword",
    )

    schema = (
        TextField("queryset"),
        TagField("tags"),
        NumericField("min_id"),
        NumericField("max_id"),
    )
    client = Client(index_name, conn=r)
    try:
        client.info()
        if getattr(settings, "CACHE_LOG", False):
            print("index exists")
    except ResponseError:
        client.create_index(schema)
    return client


def get_query_str(extra_tags, include_min_max_id=False):
    query_str_list = []
    for tag in extra_tags:
        for k, v in tag.items():
            if include_min_max_id:
                if k not in ["id", "min_id", "max_id"]:
                    condition = "{" + rf"{k}\={v}" + "}"
                    query_str = "@tags:" + condition
                    query_str_list.append(query_str)
                elif k == "min_id":
                    query_str_min_id = f"@min_id:[-inf {int(v)}]"
                    query_str_list.append(query_str_min_id)
                elif k == "max_id":
                    query_str_max_id = f"@max_id:[{int(v)} inf]"
                    query_str_list.append(query_str_max_id)
            else:
                if k not in ["min_id", "max_id"]:
                    condition = "{" + rf"{k}\={v}" + "}"
                    query_str = "@tags:" + condition
                    query_str_list.append(query_str)

    query_str = " ".join(query_str_list)
    return query_str


conn = create_redisearch_index(getattr(settings, "CACHE_INDEX", "cache_index"))


def invalidate_list(extra_tags, include_min_max_id=False):
    model_dict = {}
    real_tags = []
    for tag in extra_tags:
        if include_min_max_id:
            min_dict = {}
            max_dict = {}
            if tag.get("min_id"):
                min_dict["min_id"] = -1
                real_tags.append(min_dict)
            if tag.get("max_id"):
                max_dict["max_id"] = -1
                real_tags.append(max_dict)
        if tag.get("model_name"):
            model_dict["model_name"] = tag.get("model_name")
            real_tags.append(model_dict)

    action_dict = {"action": "list"}
    real_tags.append(action_dict)

    real_query_str = get_query_str(real_tags, include_min_max_id=include_min_max_id)

    res = conn.search(real_query_str)
    for doc in res.docs:
        conn.redis.delete(doc.id)


def check_list_or_get(query):
    # model
    model = query.model

    # extract where clauses
    where = {}
    for node in query.where.children:
        if isinstance(node.rhs, list):
            where[node.lhs.target.name] = node.rhs[0]
        else:
            where[node.lhs.target.name] = node.rhs

    primary_key = model._meta.pk.name

    for key, value in where.items():
        if key.lower() == primary_key.lower():
            return "retrieve"
    return "list"


def is_cachable(table):
    regex_list = getattr(
        settings, "CACHE_BLACKLIST", ["django_migration", "auth_", "django_content_"]
    )
    regex_string = "|".join(regex_list)
    regex = re.compile(rf"^({regex_string})\S*$", re.I | re.M)
    if re.findall(regex, table):
        return False
    return True


def get_all_tags(query, action, include_min_max_id=False):
    # extract table names
    tables_list = list(
        set([v.table_name for v in getattr(query, "alias_map", {}).values()])
    )
    if tables_list:
        tables = tables_list
    else:
        tables = [query.model._meta.db_table]

    # extract where clauses
    where = {}
    for node in query.where.children:
        if isinstance(node.rhs, list):
            where[node.lhs.target.name] = node.rhs[0]
        else:
            where[node.lhs.target.name] = node.rhs

    extra_tags = []
    # tags using where conditions
    for conditional in where:
        extra_tags.append({conditional: where[conditional]})

    # tag using action
    if action == "get" or action == "list":
        extra_tags.append({"action": action})

    # tag using the query tables
    for table in tables:
        extra_tags.append({"model_name": table})

    if include_min_max_id:
        for tag in extra_tags:
            for k, v in tag.items():
                if k == "id":
                    extra_tags.append({"min_id": int(v)})
                    extra_tags.append({"max_id": int(v)})

    return extra_tags


def get_all_tags_str(query, action):
    tag_str_list = []
    extra_tags = get_all_tags(query, action)
    for tag in extra_tags:
        for k, v in tag.items():
            tag_str_list.append(f"{k}={v}")
    tag_str = ",".join(tag_str_list)
    return tag_str


def monkey_patch_get(original_function, action):
    @wraps(original_function)
    def cache_functionality(cls, *args, **kwargs):
        # handle if sqlquery is none
        result_type = kwargs.get("result_type", MULTI)
        try:
            sql, params = cls.as_sql()
            if not sql:
                raise EmptyResultSet
        except EmptyResultSet:
            if result_type == MULTI:
                return iter([])
            else:
                return

        # key
        key = sql % params

        # extract data from query
        query = cls.query.clone()
        db_table_name = query.model._meta.db_table

        if action == "get_list":
            action_ = check_list_or_get(query)

        # main caching logic
        # check if queryset in cache
        # ==============================
        if conn.redis.exists(key):
            print('===CACHE HIT===')
            pval = conn.redis.hgetall(key)
            
            val = json.loads(pval[b'queryset'])
            # val = eval(pval[b"queryset"])
        # ==============================

        elif is_cachable(db_table_name):
            # run query on db
            val = original_function(cls, *args, **kwargs)

            # ignore if the result type is cursor since
            # this is only returned when the request type
            # is PUT and PATCH
            if isinstance(val, CursorDebugWrapper):
                return val

            # tag the created key value pair
            # add key value pair to cache with tags
            # ==============================
            if type(val) == tuple:
                max_id, min_id = -1, -1
            elif val == []:
                return val
            else:
                tval = val[0]
                min_id = tval[0][0]
                max_id = tval[-1][0]

            # val_str = str(val)
            val_str = json.dumps(val)

            tag_str = get_all_tags_str(query, action_)
            redis_key_val = {
                "queryset": val_str,
                "tags": tag_str,
                "min_id": min_id,
                "max_id": max_id,
            }

            conn.redis.hset(key, mapping=redis_key_val)
            if getattr(settings, "CACHE_LOG", False):
                print("=== CACHE MISS ===")
                print(key)
                print(tag_str)
                print("==================")
            # ==============================

        else:
            val = original_function(cls, *args, **kwargs)

        return val

    return cache_functionality


def monkey_patch_invalidate(original_function, action):
    @wraps(original_function)
    def cache_functionality(cls, *args, **kwargs):
        # handle case if sqlquery is none
        result_type = kwargs.get("result_type", MULTI)
        try:
            sql = cls.as_sql()
            if not sql:
                raise EmptyResultSet
        except EmptyResultSet:
            if result_type == MULTI:
                return iter([])
            else:
                return

        # key
        if action == "post":
            query = cls.query.clone()
            action_ = "post"
            # ==============================
            extra_tags = get_all_tags(query, action_)
            if getattr(settings, "CACHE_LOG", False):
                print("==== CACHE INVALIDATED ====")
                print(sql[0][0] % sql[0][1])
                
                print(extra_tags)
                print("===========================")
            invalidate_list(extra_tags)
            # ==============================

        else:
            sql, params = cls.as_sql()
            action_ = action
            query = cls.query.clone()
            # ==============================
            extra_tags = get_all_tags(query, action_, include_min_max_id=True)
            query_str = get_query_str(extra_tags, include_min_max_id=True)
            if getattr(settings, "CACHE_LOG", False):
                print("==== CACHE INVALIDATED ====")
                print(sql % params)
                print(extra_tags)
                print(query_str)
                print("===========================")
            res = conn.search(query_str)
            for doc in res.docs:
                conn.redis.delete(doc.id)
            invalidate_list(extra_tags, include_min_max_id=True)
            # ==============================

        val = original_function(cls, *args, **kwargs)
        return val

    return cache_functionality


def start_cache():
    print('=================sjdf========================')
    insert_sql = compiler.SQLInsertCompiler  # post
    delete_sql = compiler.SQLDeleteCompiler  # delete
    update_sql = compiler.SQLUpdateCompiler  # put,patch
    select_compiler = compiler.SQLCompiler  # get

    insert_sql.execute_sql = monkey_patch_invalidate(insert_sql.execute_sql, "post")
    delete_sql.execute_sql = monkey_patch_invalidate(delete_sql.execute_sql, "delete")
    update_sql.execute_sql = monkey_patch_invalidate(update_sql.execute_sql, "update")
    select_compiler.execute_sql = monkey_patch_get(
        select_compiler.execute_sql, "get_list"
    )