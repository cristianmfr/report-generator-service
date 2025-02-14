# coding: utf-8
from sqlalchemy import ARRAY, Boolean, Column, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Table, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
metadata = Base.metadata


# TODO: Add models generator here