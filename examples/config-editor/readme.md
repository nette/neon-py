# A configuration editor: a form over a NEON file

Use case number one: an admin panel shows the options of `config.neon` as the fields of a form,
the user changes two of them and saves, and the file keeps its comments, its blank lines and
everything the user did not touch.

**You will learn:**

- how to list the options of a file with their paths, types and comments
- why saving all fields of a form changes only those the user changed

```shell
uv run python examples/config-editor/editor.py
```

## Load, edit, save (editor.py)

```
mail.host      str      smtp.example.com   outgoing server
mail.port      int      587
mail.secure    bool     True
cache.enabled  bool     True
cache.ttl      int      3600               seconds
cache.paths.0  str      temp/cache

- 	port: 587
+ 	port: 465
- 	enabled: true
+ 	enabled: false
```

The fields come from the tree, not from the value: the tree knows the comment that explains an
option and could tell the type a schema would expect. The form submits every field, and every
one is written with `set_value()`; four of them carry the value they already had, and writing an
equal value changes nothing, so the diff holds the two changes and nothing else. `secure: yes`
stays `yes`, though the form sent `True`.
