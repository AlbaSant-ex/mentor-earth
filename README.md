# mentor-earth

Sistema de mentoría para un grupo de investigación, hecho con Django. Los mentores voluntarios se apuntan con tres clics, los mentorizados eligen mentor directamente entre los perfiles disponibles, y ambos reciben un aviso cuando se crea o se termina una pareja.

## Reglas del programa

- Cada mentor elige cuántas personas mentoriza: 1 o 2 (`MAX_MENTEES_PER_MENTOR`).
- Elegir mentor es inmediato, sin paso de aprobación. Cada persona tiene como mucho un mentor a la vez.
- Se puede ser mentor y mentorizado al mismo tiempo.
- Cualquiera de los dos puede terminar la relación en cualquier momento, sin dar motivo.
- Las relaciones terminan automáticamente a los 4 meses (`MENTORING_RELATIONSHIP_DURATION_DAYS`, 120 días). Ejecutar `manage.py expire_relationships` a diario (cron) para aplicar los vencimientos y avisar a ambas partes.
- Un mentor puede pausar (mantiene sus mentorizados pero deja de aparecer en la búsqueda), dejar de ser mentor o abandonar el programa por completo.
- Los mentores llenos o en pausa no aparecen en la búsqueda; al liberarse una plaza vuelven a aparecer solos.
- Los datos de contacto solo se muestran dentro de una relación activa.

## Puesta en marcha

```sh
uv sync
uv run manage.py migrate
uv run manage.py createsuperuser          # cuenta de administración
uv run manage.py invite ana@centro.org ben@centro.org   # o --file emails.txt
uv run manage.py runserver
```

El acceso es solo por invitación: cada persona escribe su email y recibe un código de 6 dígitos válido durante 10 minutos. En desarrollo no se envía ningún correo; el código aparece en la consola del servidor. La primera vez se pide nombre, tema de investigación y etapa de carrera.

También se puede invitar desde `/admin/` (añadir un usuario con su email) y hay un panel resumen para staff en `/staff/`.

## Tests

```sh
uv run manage.py test
```

## Configuración (variables de entorno)

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `SECRET_KEY` | clave de desarrollo | Obligatoria en producción |
| `DEBUG` | `true` | Poner `false` en producción |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Dominios, separados por comas |
| `CSRF_TRUSTED_ORIGINS` | vacío | p. ej. `https://mentoring.centro.org` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | consola | SMTP para enviar los códigos |
| `DEFAULT_FROM_EMAIL` | `mentoring@localhost` | Remitente |
| `MAX_MENTEES_PER_MENTOR` | `2` | Máximo de mentorizados por mentor |
| `MENTORING_RELATIONSHIP_DURATION_DAYS` | `120` | Duración (~4 meses) antes del cierre automático |
| `SQLITE_PATH`, `MEDIA_ROOT` | dentro del proyecto | Dónde guardar la base de datos y las fotos |

En producción hay que ejecutar `collectstatic` y servir `staticfiles/` y `media/` desde el servidor web; Django solo los sirve con `DEBUG=true`.

## Estructura

- `accounts/`: usuario (email como identificador), códigos de acceso, bienvenida y comando `invite`.
- `mentoring/models.py`: `MentorProfile`, `MentoringRelationship` (con historial) y `Notification`.
- `mentoring/services.py`: todas las reglas y transiciones de estado. Las vistas no modifican los modelos directamente.
- `templates/`, `static/css/app.css`: interfaz, sin dependencias ni paso de compilación.
