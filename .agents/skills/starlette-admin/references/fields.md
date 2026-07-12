# Fields: details and custom field types

Fields are plain Python dataclasses; every constructor argument is a dataclass field. See the quick map in SKILL.md for the full catalog. This file covers the details that the map omits and how to build custom fields.

## Attribute notes

- `default` accepts a static value, a zero-argument callable, or a request-aware callable: `StringField("locale", default=lambda request: request.state.admin_user.locale)`.
- `extra` is a free `dict` the framework never reads or writes; attach integration metadata without subclassing.
- Visibility flags per field: `exclude_from_list`, `exclude_from_detail`, `exclude_from_create`, `exclude_from_edit`, `exclude_from_export`, `exclude_from_import` (all default `False`). The view-level `exclude_fields_from_*` lists do the same by name.
- `FloatField` renders a plain text input coerced to float; it does not support `min`/`max`/`step` (use `IntegerField` or `DecimalField` for those).
- `SlugField(populate_from=...)` auto-fills client-side from another field on the same form; manual edits stop the auto-fill. `populate_from` is required.
- `ComputedField` is virtual and read-only: pass `fn=lambda obj: ...` or subclass and override `compute(obj)`. Automatically excluded from create forms, non-editable, non-searchable, non-orderable.
- `EnumField(multiple=True)` renders a select2 multi-select and stores a list. `TimeZoneField`, `CountryField`, `CurrencyField` are `EnumField` subclasses backed by Babel data (i18n extra).
- `JSONField` renders a tree/code editor storing a `dict`; pass a JSON Schema to `validation_schema` for client-side feedback.
- `DateTimeField(output_format=...)` accepts Babel formats (`"short"`, `"medium"`, `"long"`, `"full"`, or custom) and converts timezones automatically when timezone support is enabled.
- `TinyMCEEditorField` (tinymce extra): `height`, `menubar`, `statusbar`, `toolbar`, plus any native TinyMCE config via `extra_options`.

## Custom fields

Subclass the closest existing field and override only what differs. Three data methods move values between model and browser; five template paths control rendering.

### Presentation-only customization (template swap)

```python
from dataclasses import dataclass
from dataclasses import field as dc_field
from starlette_admin.fields import EnumField


@dataclass
class StatusBadgeField(EnumField):
    list_template: str = "employee/status_badge.html"
    detail_template: str = "employee/status_badge.html"
    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "Online": "badge bg-success-lt",
            "Busy": "badge bg-danger-lt",
            "Offline": "badge",
        }
    )
```

```html
{# templates/employee/status_badge.html #}
<span class="{{ field.badge_class_by_value.get(data, 'badge') }}">{{ data }}</span>
```

Point `Admin(templates_dir="templates/")` at the directory. Extending `EnumField` keeps `choices`, form validation, and the default select form template for free.

### Data methods

| Method | Called when | Default |
| --- | --- | --- |
| `parse_form_data(request, form_data)` | Form submitted | `form_data.get(self.id)` unchanged |
| `parse_obj(request, obj)` | Reading a value off a model instance | `getattr(obj, self.name, None)` |
| `serialize_value(request, value)` | Formatting for list, detail, API, export | passthrough |

Override them when the value must be computed or reshaped, not just re-rendered. Branch on `request.state.action` (a `RequestAction`) when the shape differs per context. Whatever `serialize_value` returns for `RequestAction.LIST` and `RequestAction.RELATION_LOOKUP` goes straight into a JSON response, so it must be JSON-serializable.

### Template attributes

| Attribute | Default | Context |
| --- | --- | --- |
| `list_template` | `fields/list/text.html` | List cell |
| `detail_template` | `fields/detail/text.html` | Detail row |
| `form_template` | `fields/form/input.html` | Create/edit input (also receives `error` and `action`) |
| `null_template` | `fields/detail/_null.html` | Value is `None` |
| `empty_template` | `fields/detail/_empty.html` | Value is an empty list/tuple |

All receive `field` and `data`. `data` is never None/empty in `list_template`/`detail_template`; those cases route to the null/empty templates first.

### Converter registry (string names to custom fields)

Needed only when `fields = ["status"]` should auto-resolve to your custom field. Subclass the backend converter and pass it to the view:

```python
from starlette_admin.contrib.sqla.converters import ModelConverter
from starlette_admin.converters import converts


class MyModelConverter(ModelConverter):
    @converts("Enum")   # sqla keys are column type NAMES: "String", "Integer", "Enum", ...
    def conv_enum(self, *args, **kwargs):
        _type = kwargs["type"]
        return StatusBadgeField(**self._field_common(*args, **kwargs), enum=_type.enum_class)


admin.add_view(EmployeeView(Employee, converter=MyModelConverter()))
```

Runnable example: `examples/advanced/05-custom-fields` (includes an `AvatarNameField` with data-method overrides).
