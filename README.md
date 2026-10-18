# babble for Home Assistant

Brings [babble](https://github.com/JoelBrenstrum/babble), the baby tracker, into Home Assistant. Each baby becomes a device with sensors for sleep, feeds, nappies and growth, plus switches and actions to log from Home Assistant.

## Install

1. In HACS, open the menu, choose **Custom repositories** and add `https://github.com/JoelBrenstrum/babble-home-assistant` as an **Integration**.
2. Download **babble** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and pick **babble**.
4. Enter the address you use to open babble.
5. Home Assistant shows a code and a link. Open the link on a phone or computer that's signed in to babble and approve the code.

Home Assistant signs in as the person who approved it, so it can see and log whatever they can. It then appears in babble under **Settings → Signed-in devices**, where you can rename it or sign it out. If you sign it out, Home Assistant asks you to sign in again.

The babble server must have device sign-in turned on, which needs its Supabase service role key.

## Entities

Entity IDs below use a baby called Olive.

| Entity | What it shows |
| --- | --- |
| `binary_sensor.olive_asleep` | On while a sleep is running, including while it's paused for a wake-up. |
| `binary_sensor.olive_feeding` | On while a breastfeed is running or paused. |
| `binary_sensor.olive_feed_overdue` | On once the next feed is due. Stays off overnight if feed reminders are quiet at night. |
| `sensor.olive_current_sleep` | Minutes asleep in the current sleep, leaving out pauses. |
| `sensor.olive_sleep` | `active`, `paused` or `none`, with the current and previous sleep as attributes. |
| `sensor.olive_awake_since` | When the baby last woke. |
| `sensor.olive_next_feed_due` | When the next feed is due, from the feed reminder interval set in babble. |
| `sensor.olive_last_feed` | When the last breastfeed or bottle started. |
| `sensor.olive_next_breast_side` | `left` or `right`. |
| `sensor.olive_breastfeed` | `active`, `paused` or `none`, with minutes on each side. |
| `sensor.olive_last_bottle`, `sensor.olive_last_solids`, `sensor.olive_last_nappy`, `sensor.olive_last_growth` | When each was last logged, with its details as attributes. |
| `sensor.olive_pumping` | `active`, `paused` or `none`, with the last session. |
| `sensor.olive_weight`, `sensor.olive_length`, `sensor.olive_head` | The latest measurement, with its WHO percentile. |
| `sensor.olive_sleep_today`, `sensor.olive_naps_today`, `sensor.olive_feeds_today`, `sensor.olive_bottle_today`, `sensor.olive_wet_nappies_today`, `sensor.olive_dirty_nappies_today` | Totals since the start of the baby's day. |
| `sensor.olive_predicted_next_sleep`, `sensor.olive_predicted_next_feed` | babble's predictions. Unavailable unless the family has them. |
| `sensor.olive_profile` | Name, birth date, age and time zone. |
| `switch.olive_sleep_timer` | Start or end a sleep. |
| `switch.olive_breastfeed_left`, `switch.olive_breastfeed_right` | Start, resume or switch to a side, or end the feed. |

babble is polled every 30 seconds. Durations and Feed overdue update every minute in between.

## Actions

Every action takes the baby's `device_id`.

- Sleep: `babble.start_sleep`, `pause_sleep`, `resume_sleep`, `end_sleep`, `cancel_sleep`
- Breastfeeding: `babble.start_nursing`, `pause_nursing`, `resume_nursing`, `switch_nursing_side`, `end_nursing`, `cancel_nursing`
- Logging: `babble.log_bottle`, `log_nappy`, `log_solids`, `log_pump`, `log_growth`

Starts and logs take an optional `started_at`, and ends take an optional `ended_at`, for something that happened earlier.

## Examples

### Quiet the doorbell during naps

```yaml
alias: Quiet doorbell while baby naps
mode: restart
triggers:
  - trigger: state
    entity_id: binary_sensor.olive_asleep
actions:
  - if:
      - condition: state
        entity_id: binary_sensor.olive_asleep
        state: "on"
    then:
      - action: switch.turn_off
        target:
          entity_id: switch.front_door_chime
    else:
      - action: switch.turn_on
        target:
          entity_id: switch.front_door_chime
```

If Home Assistant can't reach babble, the sensor becomes unavailable and the chime is turned back on.

### Fridge dashboard

```yaml
type: markdown
content: >
  {% set asleep = is_state('binary_sensor.olive_asleep', 'on') %}
  {% set due = states('sensor.olive_next_feed_due') %}
  ## {{ 'Asleep' if asleep else 'Awake' }}
  {% if asleep %}
  Since {{ as_timestamp(state_attr('sensor.olive_current_sleep', 'started_at')) | timestamp_custom('%H:%M') }},
  {{ states('sensor.olive_current_sleep') | int }} min so far
  {% elif has_value('sensor.olive_awake_since') %}
  Since {{ as_timestamp(states('sensor.olive_awake_since')) | timestamp_custom('%H:%M') }}
  {% endif %}

  ## Next feed {{ as_timestamp(due) | timestamp_custom('%H:%M') if has_value('sensor.olive_next_feed_due') else '–' }}
  {{ states('sensor.olive_next_breast_side') | capitalize }} side next
```

## Development

```sh
uv venv --python 3.13 && uv pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/pytest
```
