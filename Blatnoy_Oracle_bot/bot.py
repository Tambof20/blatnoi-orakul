import os
import random
import time
import telebot
from telebot import types
from flask import Flask, request
import threading
from datetime import datetime, timedelta
import schedule
from collections import defaultdict

# ======================= ИНИЦИАЛИЗАЦИЯ БОТА И FLASK =======================

# Получаем токен из переменных окружения
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    print("Ошибка: TELEGRAM_TOKEN не установлен!")
    

# ID администратора для отправки уведомлений (замени на свой)
ADMIN_ID = 585578360  # Здесь твой ID из кода

# Создаем бота
bot = telebot.TeleBot(TOKEN)

# Создаем Flask приложение
app = Flask(__name__)

# ======================= НОВЫЕ СТРУКТУРЫ ДАННЫХ =======================

# Хранилище для учета посещений пользователей
user_visits = defaultdict(list)  # user_id: [timestamp1, timestamp2, ...]

# Хранилище для истории игр
game_history = []  # Список словарей с информацией о завершенных играх

@app.route("/")
def home():
    return "🚀 Блатной оракул работает на Render.com!"


@app.route("/health")
def health():
    return "OK", 200


@app.route("/ping")
def ping():
    return "PONG", 200


@app.route("/status")
def status():
    return {
        "status": "online",
        "service": "blatnoi-orakul",
        "timestamp": time.time(),
        "message": "🚀 Блатной оракул работает на Render!",
        "active_users": len(user_visits),
        "games_played": len(game_history)
    }

# ======================= ИГРА В ОЧКО =======================

# ======================= ОСНОВНЫЕ СЛОВАРИ =======================
user_names = {}
user_scores = {}
dealer_scores = {}
user_bets = {}
active_games = {}

# ======================= КАРТОЧНАЯ КОЛОДА И ФУНКЦИИ ИГРЫ =======================
card_deck = [
    "2♠", "2♥", "2♦", "2♣",
    "3♠", "3♥", "3♦", "3♣",
    "4♠", "4♥", "4♦", "4♣",
    "5♠", "5♥", "5♦", "5♣",
    "6♠", "6♥", "6♦", "6♣",
    "7♠", "7♥", "7♦", "7♣",
    "8♠", "8♥", "8♦", "8♣",
    "9♠", "9♥", "9♦", "9♣",
    "10♠", "10♥", "10♦", "10♣",
    "В♠", "В♥", "В♦", "В♣",  # Валет
    "Д♠", "Д♥", "Д♦", "Д♣",  # Дама
    "К♠", "К♥", "К♦", "К♣",  # Король
    "Т♠", "Т♥", "Т♦", "Т♣",  # Туз
]


def get_card_value(card):
    if card[0] in ["2", "3", "4", "5", "6", "7", "8", "9"]:
        return int(card[0])
    elif card.startswith("10"):
        return 10
    elif card[0] in ["В", "Д", "К"]:
        return 10
    elif card[0] == "Т":
        return 11
    return 0


def calculate_hand_value(hand):
    total = 0
    aces = 0
    for card in hand:
        if card[0] == "Т":
            aces += 1
            total += 11
        else:
            total += get_card_value(card)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def deal_card():
    return random.choice(card_deck)


def create_game(user_id):
    player_hand = [deal_card(), deal_card()]
    dealer_hand = [deal_card(), deal_card()]
    active_games[user_id] = {
        "player_hand": player_hand,
        "dealer_hand": dealer_hand,
        "game_state": "player_turn",
    }
    return active_games[user_id]


def get_hand_display(hand, hide_first=False):
    if hide_first:
        return f"❓ {hand[1]}"
    return " ".join(hand)


def clean_bet_text(bet_text):
    if bet_text.lower().startswith("на "):
        bet_text = bet_text[3:].strip()
    if bet_text.lower().endswith(" на"):
        bet_text = bet_text[:-3].strip()
    bet_text = " ".join(bet_text.split())
    if not bet_text:
        return "ничего"
    return bet_text


def check_tournament_winner(user_id):
    player_score = user_scores.get(user_id, 0)
    dealer_score = dealer_scores.get(user_id, 0)
    if player_score >= 101:
        return "player"
    elif dealer_score >= 101:
        return "dealer"
    return None


# ======================= ФУНКЦИИ ИГРЫ =======================
def dealer_play_with_humor(message, user_id):
    game = active_games[user_id]
    dealer_value = calculate_hand_value(game["dealer_hand"])
    while dealer_value < 17:
        game["dealer_hand"].append(deal_card())
        dealer_value = calculate_hand_value(game["dealer_hand"])
    player_value = calculate_hand_value(game["player_hand"])
    if dealer_value > 21:
        end_round_with_humor(message, user_id, "dealer_bust")
    elif dealer_value > player_value:
        end_round_with_humor(message, user_id, "dealer_wins")
    elif dealer_value < player_value:
        end_round_with_humor(message, user_id, "player_wins")
    else:
        end_round_with_humor(message, user_id, "push")


# ======================= НОВАЯ ФУНКЦИЯ: СОХРАНЕНИЕ ИГРЫ =======================
def save_game_result(user_id, result, bet, player_value, dealer_value, player_score, dealer_score):
    """Сохраняет результат игры в историю"""
    now = datetime.now()
    
    game_data = {
        "timestamp": now,
        "datetime_str": now.strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user_id,
        "username": user_names.get(user_id, "фраерок"),
        "bet": bet,
        "result": result,
        "player_value": player_value,
        "dealer_value": dealer_value,
        "player_total_score": player_score,
        "dealer_total_score": dealer_score
    }
    
    game_history.append(game_data)
    
    # Отправляем уведомление администратору
    send_game_notification_to_admin(game_data)
    
    return game_data


def send_game_notification_to_admin(game_data):
    """Отправляет уведомление об игре администратору"""
    try:
        # Форматируем результат для читаемости
        result_map = {
            "player_wins": "Выиграл игрок",
            "dealer_wins": "Выиграл дилер",
            "player_bust": "Перебор у игрока",
            "dealer_bust": "Перебор у дилера",
            "surrender": "Игрок сдался",
            "push": "Ничья"
        }
        
        result_text = result_map.get(game_data["result"], game_data["result"])
        
        notification = (
            f"🎮 *Завершена игра в карты*\n\n"
            f"📅 *Дата и время:* {game_data['datetime_str']}\n"
            f"👤 *Игрок:* {game_data['username']}\n"
            f"🆔 *ID игрока:* {game_data['user_id']}\n"
            f"💰 *Ставка:* {game_data['bet']}\n"
            f"🎯 *Результат:* {result_text}\n"
        )
        
        bot.send_message(ADMIN_ID, notification, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")


# ======================= ФУНКЦИЯ: ЕЖЕДНЕВНАЯ СТАТИСТИКА =======================
def send_daily_stats():
    """Отправляет ежедневную статистику администратору"""
    try:
        now = datetime.now()
        cutoff_time = now - timedelta(hours=24)
        
        # Считаем уникальных пользователей за последние 24 часа
        recent_users = 0
        for user_id, visits in user_visits.items():
            if any(visit >= cutoff_time for visit in visits):
                recent_users += 1
        
        # Считаем игры за последние 24 часа
        recent_games = 0
        for game in game_history:
            if game["timestamp"] >= cutoff_time:
                recent_games += 1
        
        stats_message = (
            f"📊 *Ежедневная статистика*\n\n"
            f"⏰ *Время отправки:* {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"👥 *Уникальных пользователей за 24ч:* {recent_users}\n"
            f"🎮 *Сыграно игр за 24ч:* {recent_games}\n"
            f"📈 *Всего пользователей в истории:* {len(user_visits)}\n"
            f"📋 *Всего игр в истории:* {len(game_history)}\n"
            f"🕒 *Период:* {cutoff_time.strftime('%H:%M')} - {now.strftime('%H:%M')}"
        )
        
        bot.send_message(ADMIN_ID, stats_message, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Ошибка отправки статистики: {e}")


def schedule_daily_stats():
    """Планирует отправку ежедневной статистики"""
    # Устанавливаем время отправки (20:00 каждый день)
    schedule.every().day.at("20:00").do(send_daily_stats)
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Проверяем каждую минуту


def record_user_visit(user_id):
    """Записывает посещение пользователя"""
    user_visits[user_id].append(datetime.now())
    
    # Очищаем старые записи (старше 10 дней) чтобы не накапливать мусор
    cutoff = datetime.now() - timedelta(days=10)
    user_visits[user_id] = [visit for visit in user_visits[user_id] if visit >= cutoff]


def end_round_with_humor(message, user_id, result):
    if user_id not in active_games:
        return
    game = active_games[user_id]
    bet = user_bets.get(user_id, "ни на что")
    player_value = calculate_hand_value(game["player_hand"])
    dealer_value = calculate_hand_value(game["dealer_hand"])
    if user_id not in user_scores:
        user_scores[user_id] = 0
    if user_id not in dealer_scores:
        dealer_scores[user_id] = 0
    old_player_score = user_scores[user_id]
    old_dealer_score = dealer_scores[user_id]
    player_round_score = 0
    dealer_round_score = 0
    score_message = ""

    if result == "player_wins":
        player_round_score = player_value
        score_message = f" У тебя плюс {player_round_score} "
    elif result == "dealer_wins":
        dealer_round_score = dealer_value
        score_message = f" Я плюсую себе {dealer_round_score} "
    elif result == "player_bust":
        dealer_round_score = dealer_value
        score_message = f" Перебор у тебя! Мне плюс {dealer_round_score} очков"
    elif result == "dealer_bust":
        player_round_score = player_value
        score_message = f"Что то я пожадничал! Твои {player_round_score} очков"
    elif result == "surrender":
        dealer_round_score = dealer_value // 2
        score_message = f" Сдался,мне половину гони. Получается это {dealer_round_score} "
    elif result == "push":
        score_message = f" Ничья! Ни тебе ,ни мне"

    user_scores[user_id] = old_player_score + player_round_score
    dealer_scores[user_id] = old_dealer_score + dealer_round_score
    new_player_score = user_scores[user_id]
    new_dealer_score = dealer_scores[user_id]
    
    # ======================= СОХРАНЕНИЕ РЕЗУЛЬТАТА ИГРЫ =======================
    save_game_result(
        user_id=user_id,
        result=result,
        bet=bet,
        player_value=player_value,
        dealer_value=dealer_value,
        player_score=new_player_score,
        dealer_score=new_dealer_score
    )

    result_comments = {
        "player_wins": [
            f"Ты забрал сегодня кон. Завтра я заберу твою пайку.",
            f"Знай — в этой игре нет победителей. Только те, кто еще не проиграл.",
            f"Ты взял сегодня столько, сколько я тебе разрешил взять.",
        ],
        "dealer_wins": [
            f"Фраерок, спасибо за пополнение!.",
            f"Раз - и в дамки, ебана..",
            f"Выиграл у тебя сегодня, выиграю и завтра епт",
        ],
        "player_bust": [
            f"Перебор, сынок. На зоне за перебор бьют. В картах - просто проигрываешь.!",
            f"Отыгрался хер на скрипке, перебор у тебя",
            f"Перебор. Не по масти шелестишь, фраерок!",
        ],
        "dealer_bust": [
            f"У меня лишка.Ей богу в руки бы тебе насрать за такую раздачу.",
            f"Бля, опять у меня перебор.",
            f"Перебор... Знаешь, фраер, на зоне только два вида перебора прощают: перебор по молодости и перебор по глупости. Молодость моя прошла, осталась глупость.",
        ],
        "push": [
            f"Карты сошлись вровень. Как наши судьбы.",
            f"Карты сказали: ничья. Но жизнь говорит: ты мне должен.",
            f"Сегодня карты решили, что мы равны. Завтра я решу, что это ошибка.",
        ],
        "surrender": [
            f"Сдался без боя. Как мент на допросе. Полставки мои.",
            f"Сдался. Как в 41-ом французы.",
            f"О, сдался! Как сука на поводке!",
        ],
    }

    comment = random.choice(result_comments.get(result, ["Раунд окончен!"]))
    final_text = (
        f"{comment}\n\n"
        f"Фиксируем на бумажке:\n"
        f"Твои карты: {get_hand_display(game['player_hand'])} = {player_value}\n"
        f"Мои карты: {get_hand_display(game['dealer_hand'])} = {dealer_value}\n\n"
        f"{score_message}\n\n"
        f"Общая картина такая:\n"
        f"На кону у нас <b>{bet}</b>\n"
        f"Твой счет:  {new_player_score}\n"
        f"Мой счет:  {new_dealer_score}\n"
    )

    tournament_winner = check_tournament_winner(user_id)
    if tournament_winner:
        if tournament_winner == "player":
            final_text += f"\n Ты набрал {new_player_score} очков и сохранил <b>{bet}</b>, мои конгрателейшенс! "
        else:
            final_text += f"\n У меня {new_dealer_score} очков! Проебал ты <b>{bet}</b> как здрасте! "
        final_text += f"\n\nХочешь реванш? (/сыграем?)"
        try:
            bot.edit_message_text(
                final_text,
                message.chat.id,
                message.message_id,
                reply_markup=None,
                parse_mode="HTML",
            )
        except:
            bot.send_message(message.chat.id, final_text, parse_mode="HTML")
        if user_id in active_games:
            del active_games[user_id]
        if user_id in user_scores:
            del user_scores[user_id]
        if user_id in dealer_scores:
            del dealer_scores[user_id]
        if user_id in user_bets:
            del user_bets[user_id]
        return

    markup = types.InlineKeyboardMarkup()
    btn_continue = types.InlineKeyboardButton("Продолжаем?", callback_data="continue")
    markup.add(btn_continue)
    final_text += f"\nНу че, продолжим?"

    try:
        bot.edit_message_text(
            final_text,
            message.chat.id,
            message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception as e:
        bot.send_message(
            message.chat.id, final_text, reply_markup=markup, parse_mode="HTML"
        )

    if user_id in active_games:
        del active_games[user_id]


def update_game_display(message, user_id):
    if user_id not in active_games:
        return
    game = active_games[user_id]
    player_value = calculate_hand_value(game["player_hand"])
    player_score = user_scores.get(user_id, 0)
    dealer_score = dealer_scores.get(user_id, 0)
    bet = user_bets.get(user_id, "ни на что")
    game_text = (
        f"Играем на <b>{bet}</b>\n"
        f"У тебя всего {player_score}, у меня {dealer_score} \n"
        f"Играем дальше\n\n"
        f"Твои карты: {get_hand_display(game['player_hand'])}\n"
        f"Очков: {player_value}\n\n"
        f"Мои карты: {get_hand_display(game['dealer_hand'], hide_first=True)}\n"
        f"Первая карта скрыта\n\n"
        f"Что выбираешь?:"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_hit = types.InlineKeyboardButton("Давай карту", callback_data="hit")
    btn_stand = types.InlineKeyboardButton("Хватит", callback_data="stand")
    btn_surrender = types.InlineKeyboardButton("Сдаюсь", callback_data="surrender")
    markup.add(btn_hit, btn_stand, btn_surrender)
    try:
        bot.edit_message_text(
            game_text,
            message.chat.id,
            message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception as e:
        bot.send_message(
            message.chat.id, game_text, reply_markup=markup, parse_mode="HTML"
        )


# ======================= ОБРАБОТЧИКИ КОМАНД ИГРЫ =======================
@bot.message_handler(commands=["сыграем?"])
def new_tournament(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if user_id not in user_names:
        user_names[user_id] = message.from_user.first_name or "фраерок"
    name = user_names[user_id]
    user_scores[user_id] = 0
    dealer_scores[user_id] = 0
    if user_id in user_bets:
        del user_bets[user_id]
    if user_id in active_games:
        del active_games[user_id]
    bot.send_message(
        message.chat.id,
        f"Играть будем до 101 очка, {name}!\n"
        f"Очки считаем за выигранный кон, перебор это 0 очков.\n"
        f"Ну, решился что ли?",
        parse_mode="HTML",
    )
    msg = bot.send_message(
        message.chat.id, f"На что играем, {name}?", parse_mode="HTML"
    )
    bot.register_next_step_handler(msg, process_bet_with_humor)


def process_bet_with_humor(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if user_id not in user_names:
        user_names[user_id] = message.from_user.first_name or "фраерок"
    original_bet = message.text.strip()
    bet_text = original_bet.lower().strip()
    cleaned_bet = clean_bet_text(bet_text)
    display_bet = cleaned_bet

    if any(
        phrase in bet_text
        for phrase in ["просто так", "простотак", "да просто", "за просто так"]
    ):
        bot.send_message(
            message.chat.id,
            "Ты побереги свой 'просто так'.\nДумай еще.",
            parse_mode="HTML",
        )
        msg = bot.send_message(message.chat.id, "Так на что играем?")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif "интерес" in bet_text:
        bot.send_message(
            message.chat.id,
            "Мой интерес - твоя квартира. Но я человек добрый, даю шанс подумать еще.\nПредложи что-то попроще, пока я не передумал.",
            parse_mode="HTML",
        )
        msg = bot.send_message(message.chat.id, "Ну? Что предлагаешь?")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif any(
        phrase in bet_text
        for phrase in [
            "/поинтересоваться",
            "/погремуха",
            "/расход",
            "/не_оставь_в_беде",
            "/ссучиться",
            "/сыграем",
        ]
    ):
        bot.send_message(
            message.chat.id, "Ставка твоя голимый тухляк.\nМеняй.", parse_mode="HTML"
        )
        msg = bot.send_message(message.chat.id, "Что ставишь?")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif any(
        phrase in bet_text
        for phrase in [
            "ни на что",
            "ни начто",
            "ни что",
            "ничего",
            "ни на что не играю",
        ]
    ):
        bot.send_message(
            message.chat.id,
            "Для меня 'ничто' - это твоя жизнь. Хочешь так?\nПодумай еще, пока я в хорошем настроении.",
            parse_mode="HTML",
        )
        msg = bot.send_message(message.chat.id, "Уважаемый, не тяни.")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif any(
        phrase in bet_text for phrase in ["мое очко", "мою жопу", "мой рот", "моя жопа"]
    ):
        bot.send_message(
            message.chat.id,
            "Я с петухами в карты не играю.\nПодумай еще.",
            parse_mode="HTML",
        )
        msg = bot.send_message(message.chat.id, "А ты че задумался то?")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif any(
        phrase in bet_text
        for phrase in ["твое очко", "твою жопу", "твой рот", "твоя жопа"]
    ):
        bot.send_message(
            message.chat.id,
            f"О как!\nПринимаю! Ставка  {display_bet}.\n За базар придется отвечать...",
            parse_mode="HTML",
        )
        user_bets[user_id] = display_bet
        start_new_round(message)
        return
    else:
        bot.send_message(
            message.chat.id,
            f"Ну давай, играем на {display_bet}!\nПонеслась.., моча по трубам!",
            parse_mode="HTML",
        )
        user_bets[user_id] = display_bet
        start_new_round(message)


@bot.message_handler(commands=["продолжим?"])
def continue_tournament(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    name = user_names.get(user_id, "фраерок")
    if user_id not in user_bets:
        bot.send_message(
            message.chat.id,
            f"Игры пока нет, {name}!\nДавай начнем ее командой /сыграем?",
            parse_mode="HTML",
        )
        return
    tournament_winner = check_tournament_winner(user_id)
    if tournament_winner:
        if tournament_winner == "player":
            bot.send_message(
                message.chat.id,
                f"Ты уже выиграл, {name}! Начинаем по новой? (/сыграем?)",
                parse_mode="HTML",
            )
        else:
            bot.send_message(
                message.chat.id,
                f"Я тебя уже обставил {name}! Хочешь реванш? (/сыграем?)",
                parse_mode="HTML",
            )
        return
    bet = user_bets[user_id]
    player_score = user_scores.get(user_id, 0)
    dealer_score = dealer_scores.get(user_id, 0)
    bot.send_message(
        message.chat.id,
        f"Продолжаем игру, {name}!\n"
        f"Играем на  <b>{bet}</b>\n"
        f"Твой счет: {player_score} | Мой счет: {dealer_score}\n"
        f"Начинаем новый раунд!",
        parse_mode="HTML",
    )
    start_new_round(message)


def start_new_round(message):
    user_id = message.chat.id if hasattr(message, "chat") else message.from_user.id
    name = user_names.get(user_id, "фраерок")
    tournament_winner = check_tournament_winner(user_id)
    if tournament_winner:
        if tournament_winner == "player":
            bot.send_message(
                message.chat.id,
                f"Ты выиграл, {name}! Хочешь еще испытать судьбу? (/сыграем?)",
                parse_mode="HTML",
            )
        else:
            bot.send_message(
                message.chat.id,
                f"Уважаемый, я тебя уже выиграл, {name}! Хочешь реванш? (/сыграем?)",
                parse_mode="HTML",
            )
        return
    create_game(user_id)
    game = active_games[user_id]
    player_value = calculate_hand_value(game["player_hand"])
    player_score = user_scores.get(user_id, 0)
    dealer_score = dealer_scores.get(user_id, 0)
    bet = user_bets.get(user_id, "ни на что")
    game_text = (
        f"Играем на <b>{bet}</b>\n"
        f"У тебя всего {player_score} у меня {dealer_score}\n"
        f"Смотри на карты\n\n"
        f"Твои карты: {get_hand_display(game['player_hand'])}\n"
        f"Очков: {player_value}\n\n"
        f"Мои карты: {get_hand_display(game['dealer_hand'], hide_first=True)}\n"
        f"Первая карта скрыта\n\n"
        f"Что выбираешь?:"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_hit = types.InlineKeyboardButton("Давай карту", callback_data="hit")
    btn_stand = types.InlineKeyboardButton("Хватит", callback_data="stand")
    btn_surrender = types.InlineKeyboardButton("Сдаюсь", callback_data="surrender")
    markup.add(btn_hit, btn_stand, btn_surrender)
    if hasattr(message, "message_id"):
        try:
            bot.edit_message_text(
                game_text,
                message.chat.id,
                message.message_id,
                reply_markup=markup,
                parse_mode="HTML",
            )
        except Exception as e:
            bot.send_message(
                message.chat.id, game_text, reply_markup=markup, parse_mode="HTML"
            )
    else:
        bot.send_message(
            message.chat.id, game_text, reply_markup=markup, parse_mode="HTML"
        )


@bot.callback_query_handler(
    func=lambda call: call.data
    in ["hit", "stand", "surrender", "continue", "quit_game"]
)
def game_callback(call):
    user_id = call.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if call.data == "quit_game":
        items_deleted = reset_game_data(user_id)
        name = user_names.get(user_id, "фраерок")
        if items_deleted:
            deleted_text = ", ".join(items_deleted)
            bot.answer_callback_query(call.id, f" Сбросил {deleted_text}")
            try:
                bot.edit_message_text(
                    f" {name}, решил соскочить с игры!\n"
                    f" Сброшено: {deleted_text}.\n\n"
                    f"Хочешь начать заново? — /сыграем?",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=None,
                    parse_mode="HTML",
                )
            except:
                bot.send_message(
                    call.message.chat.id,
                    f" {name}, соскочил с игры.\n"
                    f"Сброшено: {deleted_text}.\n\n"
                    f"Хочешь начать заново? — /сыграем?",
                    parse_mode="HTML",
                )
        else:
            bot.answer_callback_query(call.id, " Нет активной игры")
        return
    if call.data == "continue":
        if user_id not in user_bets:
            bot.answer_callback_query(call.id, "Сначала сделай ставку!")
            return
        if user_id in active_games:
            del active_games[user_id]

        class SimpleMessage:
            def __init__(self, uid):
                class Chat:
                    def __init__(self, cid):
                        self.id = cid

                self.chat = Chat(uid)

        start_new_round(SimpleMessage(user_id))
        bot.answer_callback_query(call.id)
        return
    if user_id not in active_games:
        bot.answer_callback_query(call.id, "Игра не найдена")
        return
    game = active_games[user_id]
    if call.data == "hit":
        game["player_hand"].append(deal_card())
        player_value = calculate_hand_value(game["player_hand"])
        if player_value > 21:
            game["game_state"] = "game_over"
            end_round_with_humor(call.message, user_id, "player_bust")
        else:
            update_game_display(call.message, user_id)
    elif call.data == "stand":
        game["game_state"] = "dealer_turn"
        dealer_play_with_humor(call.message, user_id)
    elif call.data == "surrender":
        game["game_state"] = "game_over"
        end_round_with_humor(call.message, user_id, "surrender")
    bot.answer_callback_query(call.id)


# ======================= ОРИГИНАЛЬНЫЙ КОД ОРАКУЛА =======================
templates = {
    "default_username": [
        "На, {name}, держи мудрость...",
        "Слушай сюда, {name}, вот что скажу...",
        "Держи, {name}, лови мысль...",
        "Вот тебе, {name}, на раздумье...",
        "Запомни, {name}, эти слова...",
    ],
    "custom_name": [
        "Вот тебе наводочка, {name},",
        "Слушай внимательно, {name},",
        "Заруби себе на носу, {name},",
        "Прими к сведению, {name},",
        "Задумайся, {name}, над этим:",
    ],
    "no_name": [
        "Такая для тебя новость:",
        "Вот что скажу:",
        "Держи мысль:",
        "Слушай сюда:",
        "Запомни эти слова:",
    ],
}

когда = [
    "Когда в гривнах шакал панибрата найдёт",
    "когда свист на горе раком встанет",
    "Когда на бутыре червонец щербатым станет",
    "Когда в беспределе засуха братву накроет",
    "Когда в общаге левый шухер царём пройдёт",
    "Когда в тёмной малине фраер засветится",
    "Когда на стрелке мусор понятия примет",
    "Когда в чёрном ходу кореш в законе сядет",
    "Когда в шухере базар на волю выйдет",
    " Когда в ментовском кармане совесть проклюнется",
]

почему = [
    "Потому что хаза не спрашивает — она диктует",
    "хочешь понять — сядь на шконку, срок откинь, тогда и поговорим.",
    "Потому что на зоне один закон — или воруешь, или воруют тебя",
    "Потому что жизнь — это не малина, тут каждый фраер платит за свой косяк",
    "Потому что ветер в тюрьме не по понятиям дует — он с камеры на камеру переходит.",
    "Сучить не буду, но скажу: кто вор — тот и ответ знает.",
    "Потому что у судьбы, как у мента, свои расклады и своя правда",
    "Потому что колесо крутится — сегодня ты в верхах, завтра внизу, а почему — не нам решать.",
    'если бы все "почему" да "как" знали — зона бы пустовала, а она полна',
    "Потому что расклад такой: жизнь — не пазл картинку сам не соберешь",
]

как = [
    "Как в тихом омуте — без лишней пены, но с глубиной. Тема закрыта.",
    "Как по наколке — раз и навсегда. Точка.",
    "Как нож в масло — тихо и навсегда.",
    "Как приговор — без апелляции. Конец разговору",
    "Как замок на сундуке — открывать не тебе. Забудь",
    "Как фраер ушёл — без обратного хода",
    "Как по шаблону — без отсебятины",
    "Как в карцере — без лишних глаз и разговоров",
    "Как дым по ветру — видно, но не поймаешь",
]

кто = [
    "Тот, чьё имя на зоне шепчут, а вслух не зовут",
    "Братва, которая с нами за одном столом сидела, пока ты щи хлебал",
    "Кто вопросы задаёт — тот с ответом не всегда спит спокойно. Завязывай.",
    "Кто последний раз спрашивал — до сих пор ищет. Не повторяй.",
    "Кто знает — тот молчит. Кто спрашивает — тот лишний. Будь здоров",
    "Тот, кого в глаза не видел, а в спину не тыкали. И лучше не знать.",
]

куда = [
    "Куда все уходят, но никто не возвращается. Лучще не спрашивай.",
    "Куда ветер зоны дует — не нам менять его направление",
    "Куда последний вагон идёт — билет в один конц. Не твой маршрут",
    "Куда глаза смотрят, а ноги не доходят. Оставь как есть",
    "Куда тень падает — там и ответ, но светить туда не стоит",
    "Куда дорога кривая ведёт — прямым ходом не дойти. Выпей чаю и сиди",
]

кого = [
    "Того, чьё имя на зоне знают все, но вслух не называют",
    "Того, чьи руки чище, а слово твёрже камня",
    "Человека, на чьё молчание можно поставить жизнь",
    "Того, кто в шторм не свернёт и пайку последнюю разделит",
    " Чью спину ветер не гнёт, а уважение гнёт",
    "Чьи глаза на стрелке больше слов говорят.",
    'Братаан, чья фраза "по понятиям" — уже закон',
    "Того, кто в чужом кармане не шарит, но свой не пустит",
    "Чьё имя шепчут, когда нужна правда, а не треп.",
]

ты = [
    "я тебя на «вы» дважды предупредил. Третий раз будет без слов — по понятиям. Уважение или ходка, выбирай.",
    "«Ты» у нас только к суке обращаются. Смени пластинку, пока цел",
    "Мне «тыкали» последний раз в карцере. Тот фраер до сих пор щи хлебает через трубочку",
    " У нас, сынок, «ты» — это как перчатка в лицо. Поднимать не спешат — боятся не успеть",
    "«Ты» — это для мусора и шестёрок. Определись, кто ты, пока я не определил за тебя",
    "Каждое «ты» — как гвоздь в крышку. У меня терпения на три гвоздя. Ты уже второй забиваещь",
    "На «ты» здесь говорят только при последнем слове. Ты уверен, что хочешь услышать?",
    "Меня на «ты» звали только отец да срок. Отец в могиле, срок — отбыт. Выводы сделай сам",
    "«Ты» — это ключ от люка в подвал. Не крути его без надобности",
    "«Ты» — это как шаг на лёд, который не проверен. Следующий шаг может быть последним. Выбери, куда ступать",
]

вы = [
    "«вы» — это к барине в кабинете. У нас тут все по чину: кто по понятиям живет — тот и брат. А я не барин, я — человек закона. Говори как с равным, но не забывай дистанцию. Уважение — не в «выканье», а в честном слове",
    "«Вы» оставь для судей в мантиях. Здесь власть не в словах, а в деле. Я живу по уставу, а не по этикету. Говори прямо — ясность дороже поклонов",
    "«Вы» звучит как стук каблуков по плацу. Здесь власть другая — от взгляда и слова. Я не чиновник в кресле, я — закон в действии. Уважение покажешь делом, не речью",
    "«Вы» — как шинель мусорская: снаружи блестит, а внутри пусто. У нас иерархия проще: есть воры, есть братва, есть фраера. Я из первых. Говори по-братски, но не панибратствуй",
    " «Вы» — для тех, кто за решёткой впервые. Я здесь дом построил, не избу. Звание не титулом даётся, а кровью и сроком. Обращайся как к равному, но не забывай, кто держит порядок",
    "«Вы» — это как замок без ключа: красиво, но бесполезно. У нас ценится слово, а не форма. Я не граф, я — вор. Разговор вёл бы по сути, а не по церемониям",
    "«Вы» — звучит, будто ты с инспекцией пришёл. Здесь власть не по указу, а по праву сильного. Я этот право заслужил, а не унаследовал. Говори без лакейских поклонов — услышу",
    "«Вы» — для папских прихвостней. У нас статус определяется не словами, а поступками. Я не из благородных — я из избранных. Уважение прояви в глазах, а не в речах.",
]

sp = [
    "Кто не сидел — тот не жил.",
    "Лучше быть головой в грязи, чем жопой в облаках.",
    "Свети ворам, а не ментам: полжизни здесь, полжизни там!",
    "Ворам - по масти, мусорам - по пасти!",
    "Шоколад ни в чём не виноват. Пацан к успеху шёл. Не получилось, не фортануло",
    "Свобода — это когда тебя не ищет.",
    "Попал — не сдавай, сдался — не жалуйся!",
    "Сильному - мясо, слабому - кость!",
    "Сучья кровь не водица — не прощается",
    "Тюрьма плачет по тебе, а ты на воле",
    "Не люби деньги - погубят, не люби женщин - обманут, а люби волю.",
    "Помни: «дать по морде» и «дать в морду» — это одно и то же. А «дать по жопе» и «дать в жопу» — нет!",
    "Не плачь отец, что сын твой вор, пусть плачет тот, чей сын козел!",
    "Говори кратко, проси мало, уходи борзо!",
    "Бей первым! Бог простит, люди поймут.",
    "Не умеешь воровать, не воруй",
    "Добро должно быть с зубами, а петух с перьями",
    "Мать простит, а зона — никогда",
    "Жопа — как воля: пока своя — не ценишь, а потерял — не вернёшь",
    "Порядочный арестант в петухи не опустится, даже если жизнь на кону",
    "Нет на зоне краше, петуха на параше!",
]

keyword_lists = {
    "когда": когда,
    "почему": почему,
    "как": как,
    "кто": кто,
    "куда": куда,
    "кого": кого,
    "ты": ты,
    "вы": вы,
}


def get_response_by_keywords(question):
    question_lower = question.lower()
    if "ты" in question_lower:
        if (
            " ты " in f" {question_lower} "
            or question_lower.startswith("ты ")
            or question_lower.endswith(" ты")
        ):
            return random.choice(ты)
    found_keywords = []
    for keyword in keyword_lists:
        if keyword != " ты ":
            if (
                f" {keyword} " in f" {question_lower} "
                or question_lower.startswith(f"{keyword} ")
                or question_lower.endswith(f" {keyword}")
            ):
                found_keywords.append(keyword)
    if len(found_keywords) > 1:
        return random.choice(sp)
    elif len(found_keywords) == 1:
        return random.choice(keyword_lists[found_keywords[0]])
    else:
        return random.choice(sp)


default_nicks = {
    "male": [
        "Братан",
        "Бедолага",
        "Братишка",
        "Родной",
        "Корешь",
        "Бродяга",
        "Вацок",
        "Уцышка",
    ],
    "female": ["Родная", "Подруга", "Мамзель", "Фрау"],
}


def reset_user(user_id):
    if user_id in user_names:
        del user_names[user_id]
    return True


@bot.message_handler(commands=["ссучиться"])
def report_to_dev(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    name = user_names.get(user_id, "фраерок")
    bot.send_message(
        message.chat.id,
        f" Ну что {name}, хочешь доложить администрации об чем то?\n"
        f"Кидай маляву, и я передам ее кому надо:\n",
        parse_mode="HTML",
    )
    msg = bot.send_message(message.chat.id, "Пой птичка не стесняйся...")
    bot.register_next_step_handler(msg, process_dev_message)


def process_dev_message(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    name = user_names.get(user_id, "фраерок")
    user_message = message.text
    try:
        bot.send_message(
            585578360,
            f"Сообщение от блатного оракула\n\n"
            f"👤 От: {name} (ID: {user_id})\n"
            f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"✉️ {user_message}\n\n",
        )
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
    bot.send_message(
        message.chat.id,
        f" {name}, твои действия зафиксированы\n"
        f"«{user_message[:100]}...»\n\n"
        f"Маляву твою передали.\n"
        f"Администрация примет соответствующие меры.",
        parse_mode="HTML",
    )


def reset_game_data(user_id):
    items_deleted = []
    if user_id in active_games:
        del active_games[user_id]
        items_deleted.append("активную игру")
    if user_id in user_bets:
        del user_bets[user_id]
        items_deleted.append("ставку")
    if user_id in user_scores:
        del user_scores[user_id]
        items_deleted.append("счет игрока")
    if user_id in dealer_scores:
        del dealer_scores[user_id]
        items_deleted.append("счет дилера")
    return items_deleted


@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if user_id not in user_names:
        if message.from_user.username:
            user_names[user_id] = f"@{message.from_user.username}"
        else:
            gender_guess = (
                "female"
                if message.from_user.first_name
                and message.from_user.first_name.endswith(("а", "я", "ь"))
                else "male"
            )
            user_names[user_id] = random.choice(default_nicks[gender_guess])
    welcome_text = (
        f"Вечер в хату, {user_names[user_id]}!\n\n"
        "Не знаешь, как поступить?\n"
        "Я подскажу выход, все как положено, согласно понятиям.\n\n"
        "Можешь сразу спрашивать, но порядочный арестант сначала представляется (погремуха).\n"
        "С уважаемым человеком и разговор другой\n"
        "А можем просто в картишки перекинуться (сыграем?) \n\n"
        "        Команды:\n"
        "• /поинтересоваться - задать вопрос\n"
        "• /сыграем? - игра в 21 (надо набрать суммарно больше 101)\n"
        "• /погремуха - представиться по имени\n"
        "• /расход - закончить базар (остановить игру в карты, стереть имя)\n"
        "• /не_оставь_в_беде - справка\n"
        "• /ссучиться - связаться с администрацией (жалобы и предложения)\n"
    )
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("/поинтересоваться")
    btn2 = types.KeyboardButton("/сыграем?")
    btn3 = types.KeyboardButton("/погремуха")
    btn4 = types.KeyboardButton("/расход")
    btn5 = types.KeyboardButton("/не_оставь_в_беде")
    btn6 = types.KeyboardButton("/ссучиться")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)


@bot.message_handler(commands=["погремуха"])
def ask_name(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    current_name = user_names.get(user_id, "братишка")
    msg_text = (
        f"Пока ты не представишься я буду звать тебя {current_name}.\n"
        "Хочешь уважения, представься\n"
        "(или напиши 'нет', чтобы оставить все как есть):"
    )
    msg = bot.send_message(message.chat.id, msg_text)
    bot.register_next_step_handler(msg, process_name)


def process_name(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    name = message.text.strip()
    if name.lower() in ["нет", "no", "оставить", "так и быть", "пусть будет так"]:
        bot.send_message(
            message.chat.id,
            f"Добро, оставим как есть {user_names.get(user_id, 'на старых')} .",
        )
        return
    if (
        name
        and len(name) < 15
        and name != "/расход"
        and name != "/погремуха"
        and name != "/сыграем?"
        and name != "/ссучиться"
    ):
        user_names[user_id] = name
        bot.send_message(message.chat.id, f"Приветствую тебя {name}. С чем пожаловал?")
    else:
        bot.send_message(
            message.chat.id,
            "У порядочного арестанта должна быть погремуха!\nКак вспомнишь обращайся.",
        )
        if user_id not in user_names:
            gender_guess = (
                "female"
                if message.from_user.first_name
                and message.from_user.first_name.endswith(("а", "я", "ь"))
                else "male"
            )
            user_names[user_id] = random.choice(default_nicks[gender_guess])


@bot.message_handler(commands=["поинтересоваться"])
def ask_question(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if user_id not in user_names:
        if message.from_user.username:
            user_names[user_id] = f"@{message.from_user.username}"
        else:
            gender_guess = (
                "female"
                if message.from_user.first_name
                and message.from_user.first_name.endswith(("а", "я", "ь"))
                else "male"
            )
            user_names[user_id] = random.choice(default_nicks[gender_guess])
    name = user_names[user_id]
    msg = bot.send_message(message.chat.id, f"Выкладывай {name}, че там?")
    bot.register_next_step_handler(msg, process_question)


def get_random_template(template_type):
    if template_type in templates:
        return random.choice(templates[template_type])
    return "Вот что скажу:"


def process_question(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    question = message.text.strip()
    words = question.split()
    if (
        question
        in [
            "/поинтересоваться",
            "/погремуха",
            "/не_оставь_в_беде",
            "/расход",
            "/ссучиться",
            "/сыграем?",
        ]
        or len(words) <= 1
    ):
        bot.send_message(
            message.chat.id,
            "Вопрос как предъява, не может быть пустым!\nПиши че хотел.",
        )
        return
    if user_id not in user_names:
        if message.from_user.username:
            user_names[user_id] = f"@{message.from_user.username}"
        else:
            gender_guess = (
                "female"
                if message.from_user.first_name
                and message.from_user.first_name.endswith(("а", "я", "ь"))
                else "male"
            )
            user_names[user_id] = random.choice(default_nicks[gender_guess])
    name = user_names[user_id]
    bot.send_chat_action(message.chat.id, "typing")
    response = get_response_by_keywords(question)
    if user_id in user_names:
        name = user_names[user_id]
        if (
            message.from_user.username
            and user_names[user_id] == f"@{message.from_user.username}"
        ):
            template = get_random_template("default_username")
            bot.send_message(message.chat.id, template.format(name=name))
            bot.send_chat_action(message.chat.id, "typing")
            time.sleep(1)
            bot.send_message(message.chat.id, f"«<b>{response}</b>»", parse_mode="HTML")
        elif (
            message.from_user.username
            and user_names[user_id] != f"@{message.from_user.username}"
        ):
            template = get_random_template("custom_name")
            bot.send_message(message.chat.id, template.format(name=name))
            bot.send_chat_action(message.chat.id, "typing")
            time.sleep(1)
            bot.send_message(message.chat.id, f"«<b>{response}</b>»", parse_mode="HTML")
        else:
            template = get_random_template("no_name")
            bot.send_message(message.chat.id, template)
            bot.send_chat_action(message.chat.id, "typing")
            time.sleep(1)
            bot.send_message(message.chat.id, f"«<b>{response}</b>»", parse_mode="HTML")
    markup = types.InlineKeyboardMarkup()
    btn_yes = types.InlineKeyboardButton("Да", callback_data="ask_again")
    btn_no = types.InlineKeyboardButton("Нет", callback_data="stop_talking")
    markup.add(btn_yes, btn_no)
    bot.send_message(message.chat.id, "Еще вопросы?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if user_id not in user_names:
        user_info = bot.get_chat(user_id)
        if user_info.username:
            user_names[user_id] = f"@{user_info.username}"
        else:
            gender_guess = (
                "female"
                if user_info.first_name
                and user_info.first_name.endswith(("а", "я", "ь"))
                else "male"
            )
            user_names[user_id] = random.choice(default_nicks[gender_guess])
    name = user_names[user_id]
    if call.data == "ask_again":
        msg = bot.send_message(call.message.chat.id, "Ну задавай")
        bot.register_next_step_handler(msg, process_question)
    elif call.data == "stop_talking":
        bot.send_message(
            call.message.chat.id, f"Бывай {name}! Заходи не бойся, выходи не плачь."
        )
        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id, reply_markup=None
        )


@bot.message_handler(commands=["не_оставь_в_беде"])
def send_help(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    name = user_names.get(user_id, "родной")
    help_text = (
        f"{name}, я — блатной оракул, помогу разобраться в жизненной ситуации, или обыграю тебя в очко\n\n"
        "<b>Как пользоваться:</b>\n"
        "1. Просто напиши любой вопрос в чат\n"
        "2. Получи мудрый совет согласно понятиям\n"
        "4. Если решил донести на кого то знаю через кого передать маляву.\n"
        "5. Желательно представиться через кнопку (погремуха) тогда и диалог будет у нас другим\n"
        "6. Спрашивай сколько угодно и что угодно\n\n"
        "<b>Команды:</b>\n"
        "/start - начать общение заново\n"
        "/поинтересоваться  - начать общение, задать вопрос\n"
        "/погремуха - представиться по имени, но это по желанию)\n"
        "/не_оставь_в_беде - это справка(помощь)\n"
        "/расход - закончить разговор (стереть имя)\n"
        "/ссучиться - кинуть маляву куму (жалобы и предложения)\n"
        "/сыграем? - игра в 21 (пока сумме не будет больше 101)\n\n"
        "Консультирую 24/7 по всем вопросам!"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="HTML")


@bot.message_handler(commands=["расход"])
def stop_talking(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if user_id in user_names:
        name = user_names[user_id]
        game_items = reset_game_data(user_id)
        del user_names[user_id]
        if game_items:
            response_text = f" {name}, решил соскочить!\nигра закончена"
        else:
            response_text = f" Бывай {name}, заходи не бойся, уходи не плачь\n"
        bot.send_message(message.chat.id, response_text, parse_mode="HTML")
    else:
        game_items = reset_game_data(user_id)
        if game_items:
            deleted_game_text = ", ".join(game_items)
            response_text = (
                f" Бродяга, заявил расход!\n Сброшено: {deleted_game_text}.\n\n"
            )
        else:
            response_text = f" Жизнь ворам, фарту масти!"
        bot.send_message(message.chat.id, response_text, parse_mode="HTML")


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    record_user_visit(user_id)  # Записываем посещение
    if message.text.startswith("/"):
        return
    if user_id not in user_names:
        if message.from_user.username:
            user_names[user_id] = f"@{message.from_user.username}"
        else:
            gender_guess = (
                "female"
                if message.from_user.first_name
                and message.from_user.first_name.endswith(("а", "я", "ь"))
                else "male"
            )
            user_names[user_id] = random.choice(default_nicks[gender_guess])
    process_question(message)


# ======================= ЗАПУСК НА RENDER =======================
def run_flask():
    """Запускает Flask сервер"""
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


def run_bot():
    """Запускает Telegram бота"""
    print("🤖 Telegram бот запускается...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)


def run_scheduler():
    """Запускает планировщик для ежедневной статистики"""
    print("📅 Планировщик ежедневной статистики запущен...")
    schedule_daily_stats()


if __name__ == "__main__":
    print("🚀 Блатной оракул запущен на Render.com")
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем планировщик для ежедневной статистики
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Запускаем бота в основном потоке
    run_bot()
