# -*- coding: utf-8 -*-
"""This module contains a collection of the core data structures used in workbench.

"""

from __future__ import unicode_literals
from builtins import object, range

from collections import namedtuple
import logging

TEXT_FORM_RAW = 0
TEXT_FORM_PROCESSED = 1
TEXT_FORM_NORMALIZED = 2
TEXT_FORMS = [TEXT_FORM_RAW, TEXT_FORM_PROCESSED, TEXT_FORM_NORMALIZED]

logger = logging.getLogger(__name__)


class Span(namedtuple('Span', ['start', 'end'])):
    """Simple named tuple representing a span: a start and an end"""

    def to_dict(self):
        """Converts the span into a dictionary"""
        return {'start': self.start, 'end': self.end}

    def __iter__(self):
        for index in range(self.start, self.end + 1):
            yield index

    def __len__(self):
        return self.end - self.start + 1


class QueryFactory(object):
    """An object which encapsulates the components required to create a Query object.

    Attributes:
        preprocessor (Preprocessor): the object responsible for processing raw text
        tokenizer (Tokenizer): the object responsible for normalizing and tokenizing processed
            text
    """
    def __init__(self, sys_ent_rec, tokenizer, preprocessor=None):
        self.tokenizer = tokenizer
        self.preprocessor = preprocessor
        self.sys_ent_rec = sys_ent_rec

    def create_query(self, text):
        """Creates a query with the given text

        Args:
            text (str): Text to create a query object for

        Returns:
            Query: A newly constructed query
        """
        raw_text = text

        char_maps = {}

        # create raw, processed maps
        if self.preprocessor:
            processed_text = self.preprocessor.process(raw_text)
            maps = self.preprocessor.get_char_index_map(raw_text, processed_text)
            forward, backward = maps
            char_maps[(TEXT_FORM_RAW, TEXT_FORM_PROCESSED)] = forward
            char_maps[(TEXT_FORM_PROCESSED, TEXT_FORM_RAW)] = backward
        else:
            processed_text = raw_text

        normalized_tokens = self.tokenizer.tokenize(processed_text, False)
        normalized_text = ' '.join([t['entity'] for t in normalized_tokens])

        # create normalized maps
        maps = self.tokenizer.get_char_index_map(processed_text, normalized_text)
        forward, backward = maps

        char_maps[(TEXT_FORM_PROCESSED, TEXT_FORM_NORMALIZED)] = forward
        char_maps[(TEXT_FORM_NORMALIZED, TEXT_FORM_PROCESSED)] = backward

        query = Query(raw_text, processed_text, normalized_tokens, char_maps)
        query.system_entity_candidates = self.sys_ent_rec.get_candidates(query)
        return query

    def normalize(self, text):
        """Normalizes the given text

        Args:
            text (str): Text to process

        Returns:
            str: Normalized text
        """
        return self.tokenizer.normalize(text)

    def __repr__(self):
        return "<QueryFactory id: {!r}>".format(id(self))


class Query(object):
    """The query object is responsible for processing and normalizing raw user text input so that
    classifiers can deal with it. A query stores three forms of text: raw text, processed text, and
    normalized text. The query object is also responsible for translating text ranges across these
    forms.

    Attributes:
        text (str): the original input text
        processed_text (str): the text after it has been preprocessed. TODO: better description here
        normalized_tokens (list of str): a list of normalized tokens
        normalized_text (str): the normalized text. TODO: better description here
    """

    # TODO: look into using __slots__

    def __init__(self, raw_text, processed_text, normalized_tokens, char_maps):
        """Summary

        Args:
            raw_text (str): the original input text
            processed_text (str): the input text after it has been preprocessed
            normalized_tokens (list of dict): List tokens outputted by
                a tokenizer
            char_maps (dict): Mappings between character indices in raw,
                processed and normalized text
        """
        self._normalized_tokens = normalized_tokens
        norm_text = ' '.join([t['entity'] for t in self._normalized_tokens])
        self._texts = (raw_text, processed_text, norm_text)
        self._char_maps = char_maps
        self.system_entity_candidates = None

    @property
    def text(self):
        """The original input text"""
        return self._texts[TEXT_FORM_RAW]

    @property
    def processed_text(self):
        """The input text after it has been preprocessed"""
        return self._texts[TEXT_FORM_PROCESSED]

    @property
    def normalized_text(self):
        """The normalized input text"""
        return self._texts[TEXT_FORM_NORMALIZED]

    @property
    def normalized_tokens(self):
        """The tokens of the normalized input text"""
        return [token['entity'] for token in self._normalized_tokens]

    def get_system_entity_candidates(self, sys_types):
        """
        Args:
            sys_types (list of str): A list of entity types to select

        Returns:
            list: Returns candidate system entities of the types specified
        """
        return [e for e in self.system_entity_candidates if e.entity.type in sys_types]

    def transform_span(self, text_span, form_in, form_out):
        """Transforms a text range from one form to another.

        Args:
            text_span (Span): the text span being transformed
            form_in (int): the input text form. Should be one of TEXT_FORM_RAW, TEXT_FORM_PROCESSED
                or TEXT_FORM_NORMALIZED
            form_out (int): the output text form. Should be one of TEXT_FORM_RAW,
                TEXT_FORM_PROCESSED or TEXT_FORM_NORMALIZED

        Returns:
            tuple: the equivalent range of text in the output form
        """
        return Span(self.transform_index(text_span.start, form_in, form_out),
                    self.transform_index(text_span.end, form_in, form_out))

    def transform_index(self, index, form_in, form_out):
        """Transforms a text index from one form to another.

        Args:
            index (int): the index being transformed
            form_in (int): the input form. should be one of TEXT_FORM_RAW
            form_out (int): the output form

        Returns:
            int: the equivalent index of text in the output form
        """
        if form_in not in TEXT_FORMS or form_out not in TEXT_FORMS:
            raise ValueError('Invalid text form')

        if form_in > form_out:
            while form_in > form_out:
                index = self._unprocess_index(index, form_in)
                form_in -= 1
        else:
            while form_in < form_out:
                index = self._process_index(index, form_in)
                form_in += 1
        return index

    def _process_index(self, index, form_in):
        if form_in == TEXT_FORM_NORMALIZED:
            raise ValueError("'{}' form cannot be processed".format(TEXT_FORM_NORMALIZED))
        mapping_key = (form_in, (form_in + 1))
        try:
            mapping = self._char_maps[mapping_key]
        except KeyError:
            # mapping doesn't exist -> use identity
            return index
        # None for mapping means 1-1 mapping
        try:
            return mapping[index] if mapping else index
        except KeyError:
            raise ValueError('Invalid index')

    def _unprocess_index(self, index, form_in):
        if form_in == TEXT_FORM_RAW:
            raise ValueError("'{}' form cannot be unprocessed".format(TEXT_FORM_RAW))
        mapping_key = (form_in, (form_in - 1))
        try:
            mapping = self._char_maps[mapping_key]
        except KeyError:
            # mapping doesn't exist -> use identity
            return index
        # None for mapping means 1-1 mapping
        try:
            return mapping[index] if mapping else index
        except KeyError:
            raise ValueError('Invalid index')

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        return NotImplemented

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "<Query {}>".format(self.text)


class ProcessedQuery(object):
    """A processed query contains a query and the additional metadata that has been labeled or
    predicted.


    Attributes:
        domain (str): The domain of the query
        entities (list): A list of entities present in this query
        intent (str): The intent of the query
        is_gold (bool): Indicates whether the details in this query were predicted or human labeled
        query (Query): The underlying query object.
    """

    # TODO: look into using __slots__

    def __init__(self, query, domain=None, intent=None, entities=None, is_gold=False):
        self.query = query
        self.domain = domain
        self.intent = intent
        self.entities = entities
        self.is_gold = is_gold

    def to_dict(self):
        """Converts the processed query into a dictionary"""
        return {
            'text': self.query.text,
            'domain': self.domain,
            'intent': self.intent,
            'entities': [e.to_dict() for e in self.entities],
        }

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        return NotImplemented

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        msg = "<ProcessedQuery {!r}, domain: {!r}, intent: {!r}, {!r} entities{}>"
        return msg.format(self.query.text, self.domain, self.intent, len(self.entities),
                          ', gold' if self.is_gold else '')


class QueryEntity(object):
    """An entity with the context of the query it came from.

    TODO: account for numeric entities

    Attributes:
        text (str): The raw text that was processed into this entity
        processed_text (str): The processed text that was processed into
            this entity
        normalized_text (str): The normalized text that was processed into
            this entity
        span (Span): The character index span of the raw text that was
            processed into this entity
        processed_span (Span): The character index span of the raw text that was
            processed into this entity
        span (Span): The character index span of the raw text that was
            processed into this entity
        start (int): The character index start of the text range that was processed into this
            entity. This index is based on the normalized text of the query passed in.
        end (int): The character index end of the text range that was processed into this
            entity. This index is based on the normalized text of the query passed in.
    """

    # TODO: look into using __slots__

    def __init__(self, texts, spans, token_spans, entity):
        """Initializes a query entity object

        Args:
            texts (tuple): Tuple containing the three forms of text
            spans (tuple): Tuple containing the character index spans of the
                text for this entity for each text form
            token_spans (tuple): Tuple containing the token index spans of the
                text for this entity for each text form
        """
        self._texts = texts
        self._spans = spans
        self._token_spans = token_spans
        self.entity = entity

    @staticmethod
    def from_query(query, entity, span=None, normalized_span=None):
        """Creates a query entity using a query

        Args:
            query (Query): The query
            span (Span): The span of the entity in the query's raw text
            entity (Entity): The entity

        Returns:
            QueryEntity: the created query entity
        """

        if span:
            raw_span = span
            raw_text = query.text[span.start:span.end + 1]
            proc_span = query.transform_span(span, TEXT_FORM_RAW, TEXT_FORM_PROCESSED)
            proc_text = query.processed_text[proc_span.start:proc_span.end + 1]
            norm_span = query.transform_span(span, TEXT_FORM_RAW, TEXT_FORM_NORMALIZED)
            norm_text = query.normalized_text[norm_span.start:norm_span.end + 1]
        elif normalized_span:
            norm_span = normalized_span
            norm_text = query.normalized_text[norm_span.start:norm_span.end + 1]
            proc_span = query.transform_span(norm_span, TEXT_FORM_NORMALIZED, TEXT_FORM_PROCESSED)
            proc_text = query.processed_text[proc_span.start:proc_span.end + 1]
            raw_span = query.transform_span(norm_span, TEXT_FORM_NORMALIZED, TEXT_FORM_RAW)
            raw_text = query.text[raw_span.start:raw_span.end + 1]

        texts = (raw_text, proc_text, norm_text)
        spans = (raw_span, proc_span, norm_span)

        full_text = (query.text, query.processed_text, query.text)

        def get_token_span(full_text, span):
            """Converts a character span to a token span

            Args:
                span (Span): the character span
                full_text (str): The text in question

            Returns:
                Span: the token span
            """
            span_text = full_text[span.start:span.end + 1]
            start = len(full_text[:span.start].split())
            end = start - 1 + len(span_text.split())
            return Span(start, end)

        token_spans = tuple(map(get_token_span, full_text, spans))
        return QueryEntity(texts, spans, token_spans, entity)

    @property
    def text(self):
        """The original input text span"""
        return self._texts[TEXT_FORM_RAW]

    @property
    def processed_text(self):
        """The input text after it has been preprocessed"""
        return self._texts[TEXT_FORM_PROCESSED]

    @property
    def normalized_text(self):
        """The normalized input text"""
        return self._texts[TEXT_FORM_NORMALIZED]

    @property
    def span(self):
        """The span of original input text span"""
        return self._spans[TEXT_FORM_RAW]

    @property
    def processed_span(self):
        """The span of the preprocessed text span"""
        return self._spans[TEXT_FORM_PROCESSED]

    @property
    def normalized_span(self):
        """The span of the normalized text span"""
        return self._spans[TEXT_FORM_NORMALIZED]

    @property
    def token_span(self):
        """The token_span of original input text span"""
        return self._token_spans[TEXT_FORM_RAW]

    @property
    def processed_token_span(self):
        """The token_span of the preprocessed text span"""
        return self._token_spans[TEXT_FORM_PROCESSED]

    @property
    def normalized_token_span(self):
        """The token_span of the normalized text span"""
        return self._token_spans[TEXT_FORM_NORMALIZED]

    def to_dict(self):
        """Converts the query entity into a dictionary"""
        base = self.entity.to_dict()
        base.update({
            'text': self.text,
            'span': self.span.to_dict()
        })
        return base

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        return NotImplemented

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return "{}{}{} '{}' {}-{} ".format(
            self.entity.type, ':' if self.entity.role else '', self.entity.role, self.text,
            self.span.start, self.span.end
        )

    def __repr__(self):
        msg = '<QueryEntity {!r} ({!r}) char: [{!r}-{!r}] tok: [{!r}-{!r}]>'
        return msg.format(self.text, self.entity.type, self.span.start, self.span.end,
                          self.token_span.start, self.token_span.end)


class Entity(object):
    """Summary

    Attributes:
        type (str): The type of entity
        role (str): Description
        value (str): The resolved value of the entity
        display_text (str): A human readable text representation of the entity for use in natural
            language responses.
    """

    # TODO: look into using __slots__

    def __init__(self, entity_type, role=None, value=None, display_text=None, confidence=None):
        self.type = entity_type
        self.role = role
        self.value = value
        self.display_text = display_text
        self.confidence = confidence
        self.is_system_entity = entity_type.startswith('sys:')

    def to_dict(self):
        """Converts the entity into a dictionary"""
        base = {
            'type': self.type,
            'role': self.role,
            'value': self.value,
            'display_text': self.display_text
        }
        if self.confidence is not None:
            base['confidence'] = self.confidence

        return base

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        return NotImplemented

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "<Entity {!r} ({!r})>".format(self.display_text, self.type)


def resolve_entity_conflicts(query_entities):
    """This method takes a list containing query entities for a query, and resolves
    any entity conflicts. The resolved list is returned.

    If two facets in a query conflict with each other, use the following logic:
        - If the target facet is a subset of another facet, then delete the
          target facet.
        - If the target facet shares the identical span as another facet,
          then keep the one with the highest confidence.
        - If the target facet overlaps with another facet, then keep the one
          with the highest confidence.

    Args:
        entities (list of QueryEntity): A list of query entities to resolve

    Returns:
        list of QueryEntity: A filtered list of query entities

    """
    filtered = [e for e in query_entities]
    i = 0
    while i < len(filtered):
        include_target = True
        target = filtered[i]
        j = i + 1
        while j < len(filtered):
            other = filtered[j]
            if _is_superset(target, other) and not _is_same_span(target, other):
                logger.debug('Removing {{{1:s}|{2:s}}} facet in query {0:d} since it is a '
                             'subset of another.'.format(i, other.text, other.entity.type))
                del filtered[j]
                continue
            elif _is_subset(target, other) and not _is_same_span(target, other):
                logger.debug('Removing {{{1:s}|{2:s}}} facet in query {0:d} since it is a '
                             'subset of another.'.format(i, target.text, target.entity.type))
                del filtered[i]
                include_target = False
                break
            elif _is_same_span(target, other) or _is_overlapping(target, other):
                if target.entity.confidence >= other.entity.confidence:
                    logger.debug('Removing {{{1:s}|{2:s}}} facet in query {0:d} since it overlaps '
                                 'with another.'.format(i, other.text, other.entity.type))
                    del filtered[j]
                    continue
                elif target.entity.confidence < other.entity.confidence:
                    logger.debug('Removing {{{1:s}|{2:s}}} facet in query {0:d} since it overlaps '
                                 'with another.'.format(i, target.text, target.entity.type))
                    del filtered[i]
                    include_target = False
                    break
            j += 1
        if include_target:
            i += 1

    return filtered


def _is_subset(target, other):
    return ((target.start >= other.start) and
            (target.end <= other.end))


def _is_superset(target, other):
    return ((target.start <= other.start) and
            (target.end >= other.end))


def _is_same_span(target, other):
    return _is_superset(target, other) and _is_subset(target, other)


def _is_overlapping(target, other):
    target_range = range(target.start, target.end + 1)
    predicted_range = range(other.start, other.end + 1)
    overlap = set(target_range).intersection(predicted_range)
    return (overlap and not _is_subset(target, other) and
            not _is_superset(target, other))
