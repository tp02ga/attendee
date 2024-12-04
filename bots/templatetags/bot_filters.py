from django import template

register = template.Library()

@register.filter
def modulo(num, val):
    return int(num) % val

@register.filter
def integer_divide(num, val):
    return int(num) // val

@register.filter
def get_next(value, current_index):
    try:
        return value[current_index + 1]
    except IndexError:
        return value[current_index]  # fallback to current item if next doesn't exist 