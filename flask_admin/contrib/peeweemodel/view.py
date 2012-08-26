from flask import flash

from flask.ext.admin import form
from flask.ext.admin.babel import gettext, ngettext, lazy_gettext
from flask.ext.admin.model import BaseModelView

from peewee import PrimaryKeyField, ForeignKeyField, Field, CharField, TextField, Q
from wtfpeewee.orm import model_form

from flask.ext.admin.contrib.peeweemodel import filters
from .form import CustomModelConverter


class ModelView(BaseModelView):
    column_filters = None
    """
        Collection of the column filters.

        Can contain either field names or instances of :class:`flask.ext.admin.contrib.sqlamodel.filters.BaseFilter` classes.

        For example::

            class MyModelView(BaseModelView):
                column_filters = ('user', 'email')

        or::

            class MyModelView(BaseModelView):
                column_filters = (BooleanEqualFilter(User.name, 'Name'))
    """

    filter_converter = filters.FilterConverter()
    """
        Field to filter converter.

        Override this attribute to use non-default converter.
    """

    def __init__(self, model, name=None,
                 category=None, endpoint=None, url=None):
        super(ModelView, self).__init__(model, name, category, endpoint, url)

        self._primary_key = self.scaffold_pk()

    def _get_model_fields(self, model=None):
        if model is None:
            model = self.model

        return model._meta.get_sorted_fields()

    def scaffold_pk(self):
        for n, f in self._get_model_fields():
            if type(f) == PrimaryKeyField:
                return n

        return None

    def get_pk_value(self, model):
        return getattr(model, self._primary_key)

    def scaffold_list_columns(self):
        columns = []

        for n, f in self._get_model_fields():
            # Filter by name
            if (self.excluded_list_columns and
                n in self.excluded_list_columns):
                continue

            # Verify type
            field_class = type(f)

            if field_class == ForeignKeyField:
                columns.append(n)
            elif field_class != PrimaryKeyField:
                columns.append(n)

        return columns

    def scaffold_sortable_columns(self):
        columns = dict()

        for n, f in self._get_model_fields():
            if type(f) != PrimaryKeyField:
                columns[n] = f

        return columns

    def init_search(self):
        self._search_fields = []

        if self.searchable_columns:
            for p in self.searchable_columns:
                if isinstance(p, basestring):
                    p = getattr(self.model, p)

                field_type = type(p)

                # Check type
                if (field_type != CharField and
                    field_type != TextField):
                        raise Exception('Can only search on text columns. ' +
                                        'Failed to setup search for "%s"' % p)

                # Try to find reference from this model to the field
                if p.model != self.model:
                    path = self._find_field(self.model, p, set())

                    if path is None:
                        raise Exception('Can not find relation path from the %s' +
                                        'to the %s.%s' % (self.model, p.model, p.name))

                    self._search_fields.append(path)
                else:
                    self._search_fields.append(p.name)

        return bool(self._search_fields)

    def _find_field(self, model, field, visited, path=None):
        def make_path(n):
            if path:
                return '%s__%s' % (path, n)
            else:
                return n

        for n, p in self._get_model_fields(model):
            if p.model == model and p.name == field.name:
                return make_path(n)

            if type(p) == ForeignKeyField:
                if p.to not in visited:
                    visited.add(p.to)

                    result = self._find_field(p.to, field, visited,
                                        make_path(n))

                    if result is not None:
                        return result

        return None

    def scaffold_filters(self, name):
        if isinstance(name, basestring):
            attr = getattr(self.model, name, None)
        else:
            attr = name

        if attr is None:
            raise Exception('Failed to find field for filter: %s' % name)

        if not isinstance(name, basestring):
            visible_name = self.get_column_name(attr.name)
        else:
            visible_name = self.get_column_name(name)

        type_name = type(attr).__name__
        flt = self.filter_converter.convert(type_name,
                                            attr,
                                            visible_name)

        if flt:
            # TODO: Related table search
            pass

        return flt

    def is_valid_filter(self, filter):
        return isinstance(filter, filters.BasePeeweeFilter)

    def scaffold_form(self):
        return model_form(self.model,
            base_class=form.BaseForm,
            only=self.form_columns,
            exclude=self.excluded_form_columns,
            field_args=self.form_args,
            converter=CustomModelConverter())

    def get_list(self, page, sort_column, sort_desc, search, filters,
                 execute=True):
        query = self.model.select()

        # Search
        if self._search_supported and search:
            terms = search.split(' ')

            for term in terms:
                if not term:
                    continue

                stmt = None
                for field in self._search_fields:
                    flt = '%s__icontains' % field
                    q = Q(**{flt: term})

                    #print flt, term

                    if stmt is None:
                        stmt = q
                    else:
                        stmt |= q

                query = query.where(stmt)

        # Filters
        if self._filters:
            for flt, value in filters:
                query = self._filters[flt].apply(query, value)

        # Get count
        count = query.count()

        # Apply sorting
        if sort_column is not None:
            sort_field = self._sortable_columns[sort_column]

            if isinstance(sort_field, basestring):
                query = query.order_by((sort_field, sort_desc and 'desc' or 'asc'))
            elif isinstance(sort_field, Field):
                query = query.order_by((sort_column, sort_desc and 'desc' or 'asc'))

        # Pagination
        if page is not None:
            query = query.offset(page * self.page_size)

        query = query.limit(self.page_size)

        if execute:
            query = query.execute()

        return count, query

    def get_one(self, id):
        return self.model.get(**{self._primary_key: id})

    def create_model(self, form):
        try:
            model = self.model()
            form.populate_obj(model)
            model.save()
            return True
        except Exception, ex:
            flash(gettext('Failed to create model. %(error)s', error=str(ex)), 'error')
            return False

    def update_model(self, form, model):
        """
            Update model from form.

            `form`
                Form instance
        """
        try:
            form.populate_obj(model)
            model.save()
            return True
        except Exception, ex:
            flash(gettext('Failed to update model. %(error)s', error=str(ex)), 'error')
            return False

    def delete_model(self, model):
        try:
            model.delete_instance(recursive=True)
            return True
        except Exception, ex:
            flash(gettext('Failed to delete model. %(error)s', error=str(ex)), 'error')
            return False
