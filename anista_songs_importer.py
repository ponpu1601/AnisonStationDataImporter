# -*- coding: utf-8 -*-

import configparser
import csv
import re
import sys
from datetime import datetime
from enum import IntEnum
from operator import itemgetter

import dataset
import dateutil.parser
# ドライバをimport
import mysql.connector


class Fields_Index(IntEnum):
    PROGRAM_ID = 0
    PROGRAM_TYPE = 1
    PROGRAM_TITLE = 2
    SONG_ROLE = 3
    BROADCASTED_ORDER = 4
    SONG_ID = 5
    TITLE = 6
    SINGER = 7

def dump_config(conf):
    print(conf.get('database','user'))
    print(conf.get('database','passwd'))
    print(conf.get('database','db'))
    print(conf.get('database','host'))
    print(conf.get('database','port'))
    print(conf.get('database','charaset'))

def load_config():
    inifile = configparser.ConfigParser()
    inifile.read('config.ini','UTF-8')
    dump_config(inifile)
    return inifile

def get_song_roles(cursor):
    sql='select id , code , name from song_roles;'
    cursor.execute(sql)
    return cursor.fetchall()

def get_singers(cursor):
    sql='select id , name from singers;'
    cursor.execute(sql)
    return cursor.fetchall()

def get_programs_limit(cursor,start_id):
    sql='select * from programs where anisoninfo_program_id >= %s order by anisoninfo_program_id limit 200;'
    cursor.execute(sql,(start_id,))
    return cursor.fetchall()

def ensure_program_id(cursor,anisoninfo_program_id):
    sql='select * from programs where anisoninfo_program_id = %s;'
    cursor.execute(sql,(anisoninfo_program_id,))
    program = cursor.fetchone()
    if program == None:
        store_program(cursor,anisoninfo_program_id)
        return cursor.lastrowid
    else:
        return program['id']


def store_program(cursor,program_id):
    sql='insert into programs (anisoninfo_program_id) values (%s);'
    cursor.execute(sql,(program_id,))
    pass

def ensure_object_key_integer(obj_dictionary_list,target_obj,compared_key):
    matched_obj = [obj for obj in obj_dictionary_list if re.fullmatch(re.escape(str(target_obj[compared_key])),re.escape(str(obj[compared_key])))]
    if len(matched_obj)!=0:
        return matched_obj[0]
    else:
        target_obj['id'] = get_last_item_id(obj_dictionary_list) + 1
        target_obj['title'] = ''
        obj_dictionary_list.append(target_obj)
        return target_obj
        

def ensure_object(obj_dictionary_list,target_obj,compared_key):
    # MySQLは大文字小文字を区別しないため、ここで判定しないとDB登録時に重複している判断される
    # 現在のcsvの仕様では歌手名はテーブル分けないほうがいいかもしれない
    matched_obj = [obj for obj in obj_dictionary_list if str(target_obj[compared_key]).lower()==str(obj[compared_key]).lower()]
    if len(matched_obj)!=0:
        return matched_obj[0]
    else:
        target_obj['id'] = get_last_item_id(obj_dictionary_list) + 1
        obj_dictionary_list.append(target_obj)
        return target_obj
        
def get_last_item_id(obj_dictionary_list):
    last_item = sorted(obj_dictionary_list,key=itemgetter('id'),reverse=True)[0]
    return last_item['id']

def upsert_song_role(cursor,dictionary):
    insert_dup = 'insert into song_roles (id , code) values ( %(id)s , %(code)s ) on duplicate key update name = %(name)s'
    cursor.execute(insert_dup,dictionary)
    pass

def upsert_singer(cursor,dictionary):
    insert_dup = 'insert into singers (id , name) values ( %(id)s , %(name)s ) on duplicate key update name = %(name)s'
    cursor.execute(insert_dup,dictionary)
    pass

def upsert_program(cursor,dictionary):
    insert_dup = 'insert into programs (id , anisoninfo_program_id) values ( %(id)s , %(anisoninfo_program_id)s ) on duplicate key update title = %(title)s'
    cursor.execute(insert_dup,dictionary)
    pass

def upsert_song(cursor,song):
    insert_dup = 'insert into songs (' + \
                 'title , anisoninfo_song_id , program_id , song_role_id , singer_id' + \
                 ') values ('+\
                 '%(title)s , %(anisoninfo_song_id)s , %(program_id)s , %(song_role_id)s , %(singer_id)s' + \
                 ') on duplicate key update ' + \
                 'title = %(title)s , anisoninfo_song_id = %(anisoninfo_song_id)s ,' + \
                 'song_role_id = %(song_role_id)s , program_id = %(program_id)s , singer_id = %(singer_id)s;'
    cursor.execute(insert_dup,song)
    pass

def ensure_date(target):
    tmp = target
    try:
        dateutil.parser.parse(tmp)
        return target
    except:
        return '0000-00-00'

def parse_song(field,song_role_id,singer_id,program_id):
    return {
        'program_id':program_id,
        'song_role_id':song_role_id,
        'anisoninfo_song_id':field[Fields_Index.SONG_ID],
        'title':field[Fields_Index.TITLE],
        'singer_id':singer_id,
    }

def load_csv(reader):
    # ヘッダーを飛ばす
    header = next(reader)
    print(header)
    # 一気に読み込む
    fields = []
    for row in reader:
        fields.append(row)
    return fields


print ('starting program at',datetime.now())

conf = load_config()

# コマンドラインからのファイルパスを取得
args = sys.argv
file_path = args[1]

# csv読み込み
csv_file = open(file_path,'r',encoding='utf8')
reader = csv.reader(csv_file , delimiter=',',doublequote=True,lineterminator="\r\n",quotechar='"',skipinitialspace=True)

#一気に読み込む
fields = load_csv(reader)
print('csv_file was loaded at',datetime.now())

# データベースに接続
try:
    connect = mysql.connector.connect( \
        user=conf.get('database','user'), passwd=conf.get('database','passwd'), host=conf.get('database','host'), \
        port=conf.getint('database','port'), db=conf.get('database','db'),charset=conf.get('database','charaset') \
        )
    cursor = connect.cursor(buffered=True,dictionary=True)

    # マスターを取得
    song_roles = get_song_roles(cursor)
    singers = get_singers(cursor)
    programs = get_programs_limit(cursor,0)
    max_aniin_program = max(programs,key=lambda program: int(program['anisoninfo_program_id']))
    programs_range = 0

    # 一括upsert用のdictionaryリストを作成
    sorted_fields=sorted(fields,key=lambda field:(int(field[Fields_Index.PROGRAM_ID])))

    songs = []
    for field in sorted_fields:
        # 摘要をマスターから取得　なかったら作る
        tmp_song_role = {'code':field[Fields_Index.SONG_ROLE]}
        song_role = ensure_object(song_roles,tmp_song_role,'code')
        #print('fetched song_role at',datetime.now())
        # 歌手をマスターから取得　無かったら作る
        tmp_singer = {'name':field[Fields_Index.SINGER]}
        singer = ensure_object(singers,tmp_singer,'name')
        #print('fetched singer at',datetime.now())

        # Programsのanisoninfo_idの最大値までParseしたらProgramsを再取得
        if int(field[Fields_Index.PROGRAM_ID]) >= max_aniin_program['anisoninfo_program_id']:
            programs_range =int(field[Fields_Index.PROGRAM_ID])
            tmp_programs = get_programs_limit(cursor,programs_range)
            if len(tmp_programs) != 0:
                programs=tmp_programs
                max_aniin_program = max(programs,key=lambda program: int(program['anisoninfo_program_id']))
                print('fetch 200 programs from %s max %s at'%(programs_range,max_aniin_program['anisoninfo_program_id']),datetime.now())
            else:
                print('current row',field)
        
        # anisoninfo_program_idをマスターから取得　無かったら作る
        tmp_anisoninfo_program = {'anisoninfo_program_id':field[Fields_Index.PROGRAM_ID]}
        program = ensure_object_key_integer(programs,tmp_anisoninfo_program,'anisoninfo_program_id')
        #print('fetched program at',datetime.now())
        # csvのフィールドをsongにパースして追加
        song = parse_song(field,song_role['id'],singer['id'],program['id'])
        songs.append(song)
    
    print('csv_file was parsed at',datetime.now())
    
    # それぞれのマスターを更新
    for song_role in song_roles:
        upsert_song_role(cursor,song_role)

    for singer in singers:
        upsert_singer(cursor,singer)
    
    for program in programs:
        upsert_program(cursor,program)

    # song.csv内にマスター新規追加分があった場合にデータベース上に
    # それぞれのエンティティが必要なためコミット
    connect.commit()
    print('masters were committed at',datetime.now())

    # songsを挿入
    for song in songs:
        upsert_song(cursor,song)

    connect.commit()
    print('songs(count:%s) were committed at' % len(songs),datetime.now())
finally:
    cursor.close
    connect.close

print ('terminating program at',datetime.now())