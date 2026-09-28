# Картографічні дані

`europe-basemap.geojson` містить спрощені сучасні контури для автономних HTML-карт:

- 25 адміністративних одиниць України взято з [`darmat1/ukraine-geo-data`, `Ukraine.geojson`](https://github.com/darmat1/ukraine-geo-data/blob/main/geodata/Ukraine.geojson), побудованого на даних OpenStreetMap. © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright). Геометрію спрощено (відстань між послідовними точками приблизно 0,012°), додаткові атрибути вилучено. Ця частина даних поширюється за ODbL.
- Контури інших країн Європи, РФ, Туреччини та Грузії взято з [`Natural Earth`, `ne_110m_admin_0_countries.geojson`](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson); набір є [суспільним надбанням](https://www.naturalearthdata.com/about/terms-of-use/). Поля атрибутів скорочено, координати округлено.

Атрибуцію виведено безпосередньо на картах. Сучасні контури не відтворюють
історичний адміністративний поділ; координати міст з `config/geography.yaml`
позначають орієнтовні центри й не визначають місця подій зі справ.
