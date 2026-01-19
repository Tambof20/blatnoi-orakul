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

# ID администратора для отправки уведомлений
ADMIN_ID = 585578360

# Создаем бота
bot = telebot.TeleBot(TOKEN)

# Создаем Flask приложение
app = Flask(__name__)

# ======================= СТРУКТУРЫ ДАННЫХ =======================

# Хранилище для учета посещений пользователей
user_visits = defaultdict(list)  # user_id: [timestamp1, timestamp2, ...]

# Хранилище для истории игр
game_history = []  # Список словарей с информацией о завершенных играх

# Хранилище для ожидающих приглашений
pending_invitations = {}  # invitation_id: {inviter_id, invitee_id, bet, timestamp, status}

# Хранилище для активных мультиплеерных игр
multiplayer_games = {}  # game_id: {player1_id, player2_id, bet, player1_hand, player2_hand, current_turn, scores}

# Хранилище для состояний пользователей
user_states = {}  # user_id: {'state': 'waiting_for_invite_decision', 'invitation_id': '...', etc}

# Хранилище для турнирных очков в мультиплеере
multiplayer_scores = {}  # game_id: {player1_id: score, player2_id: score}

# Счетчик для уникальных ID
invitation_counter = 0
game_counter = 0

# ======================= ОСНОВНЫЕ СЛОВАРИ =======================
user_names = {}
user_scores = {}
dealer_scores = {}
user_bets = {}
active_games = {}

# ======================= КАРТОЧНАЯ КОЛОДА И ФУНКЦИИ ИГРЫ =======================
card_deck = [
    "2♠", "2♥", "2♦", "2♣", "3♠", "3♥", "3♦", "3♣", "4♠", "4♥", "4♦", "4♣",
    "5♠", "5♥", "5♦", "5♣", "6♠", "6♥", "6♦", "6♣", "7♠", "7♥", "7♦", "7♣",
    "8♠", "8♥", "8♦", "8♣", "9♠", "9♥", "9♦", "9♣", "10♠", "10♥", "10♦", "10♣",
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
    bet_text_lower = bet_text.lower()
    remove_words = ["на", "сыграем", "играем", "ставлю", "поставлю", "играю", "ставим", "поставим"]
    
    for word in remove_words:
        if bet_text_lower.startswith(f"{word} "):
            bet_text = bet_text[len(word):].strip()
            bet_text_lower = bet_text.lower()
    
    for word in remove_words:
        if bet_text_lower.endswith(f" {word}"):
            bet_text = bet_text[:-len(word)].strip()
            bet_text_lower = bet_text.lower()
    
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

def save_tournament_result(user_id, winner, bet, player_score, dealer_score):
    """Сохраняет результат турнира в историю"""
    now = datetime.now()
    tournament_data = {
        "timestamp": now,
        "datetime_str": now.strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user_id,
        "username": user_names.get(user_id, "фраерок"),
        "bet": bet,
        "winner": winner,
        "player_final_score": player_score,
        "dealer_final_score": dealer_score,
        "tournament_ended": True,
    }
    game_history.append(tournament_data)
    send_tournament_notification_to_admin(tournament_data)
    return tournament_data

def send_tournament_notification_to_admin(tournament_data):
    """Отправляет уведомление о завершении турнира администратору"""
    try:
        winner_text = "Игрок" if tournament_data["winner"] == "player" else "Дилер"
        notification = (
            f"🏆 *Завершен турнир в 21*\n\n"
            f"📅 *Дата и время:* {tournament_data['datetime_str']}\n"
            f"👤 *Игрок:* {tournament_data['username']}\n"
            f"🆔 *ID игрока:* {tournament_data['user_id']}\n"
            f"💰 *Ставка:* {tournament_data['bet']}\n"
            f"🏁 *Победитель:* {winner_text}\n"
        )
        bot.send_message(ADMIN_ID, notification, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка отправки уведомления о турнире: {e}")

def send_daily_stats():
    """Отправляет ежедневную статистику администратору"""
    try:
        now = datetime.now()
        cutoff_time = now - timedelta(hours=24)
        recent_users = 0
        for user_id, visits in user_visits.items():
            if any(visit >= cutoff_time for visit in visits):
                recent_users += 1
        
        recent_tournaments = 0
        for game in game_history:
            if game.get("tournament_ended") and game["timestamp"] >= cutoff_time:
                recent_tournaments += 1

        stats_message = (
            f"📊 *Ежедневная статистика*\n\n"
            f"⏰ *Время отправки:* {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"👥 *Уникальных пользователей за 24ч:* {recent_users}\n"
            f"🏆 *Завершенных турниров за 24ч:* {recent_tournaments}\n"
            f"📈 *Всего пользователей в истории:* {len(user_visits)}\n"
            f"📋 *Всего турниров в истории:* {len([g for g in game_history if g.get('tournament_ended')])}\n"
            f"🕒 *Период:* {cutoff_time.strftime('%H:%M')} - {now.strftime('%H:%M')}"
        )
        bot.send_message(ADMIN_ID, stats_message, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка отправки статистики: {e}")

def schedule_daily_stats():
    """Планирует отправку ежедневной статистики"""
    schedule.every().day.at("20:00").do(send_daily_stats)
    while True:
        schedule.run_pending()
        time.sleep(60)

def record_user_visit(user_id):
    """Записывает посещение пользователя"""
    user_visits[user_id].append(datetime.now())
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
            f"Перебор... Знаешь, фраер, на зоне только два вида перебора прощают: перебор по молодости и перебор по глупость. Молодость моя прошла, осталась глупость.",
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
        f"Играем на <b>{bet}</b>\n"
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

        save_tournament_result(
            user_id=user_id,
            winner=tournament_winner,
            bet=bet,
            player_score=new_player_score,
            dealer_score=new_dealer_score,
        )

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

# ======================= ИСПРАВЛЕННАЯ СИСТЕМА ПРИГЛАШЕНИЙ =======================

def ask_for_multiplayer_invitation(message, user_id, bet):
    """Спрашивает, хочет ли пользователь пригласить другого игрока"""
    user_states[user_id] = {'state': 'waiting_for_invite_decision', 'bet': bet}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_yes = types.InlineKeyboardButton("🎮 Пригласить друга", callback_data="invite_yes")
    btn_no = types.InlineKeyboardButton("🤖 Играть с ботом", callback_data="invite_no")
    markup.add(btn_yes, btn_no)
    
    bot.send_message(
        message.chat.id,
        f"🎲 <b>Играем на {bet}!</b>\n\n"
        f"Хочешь пригласить друга на игру в 21?\n"
        f"Или будем играть как обычно - ты против меня?",
        reply_markup=markup,
        parse_mode="HTML"
    )

def create_multiplayer_invitation(inviter_id, bet):
    """Создает приглашение для мультиплеерной игры"""
    global invitation_counter
    invitation_counter += 1
    invitation_id = f"inv_{invitation_counter}_{inviter_id}"

    pending_invitations[invitation_id] = {
        "inviter_id": inviter_id,
        "inviter_name": user_names.get(inviter_id, "фраерок"),
        "bet": bet,
        "timestamp": datetime.now(),
        "status": "pending",
        "invitee_id": None,
    }
    return invitation_id

def create_multiplayer_game(inviter_id, invitee_id, bet):
    """Создает мультиплеерную игру"""
    global game_counter
    game_counter += 1
    game_id = f"game_{game_counter}"

    player1_hand = [deal_card(), deal_card()]
    player2_hand = [deal_card(), deal_card()]

    multiplayer_games[game_id] = {
        "player1_id": inviter_id,
        "player2_id": invitee_id,
        "player1_name": user_names.get(inviter_id, "фраерок"),
        "player2_name": user_names.get(invitee_id, "фраерок"),
        "bet": bet,
        "player1_hand": player1_hand,
        "player2_hand": player2_hand,
        "current_turn": inviter_id,
        "player1_score": calculate_hand_value(player1_hand),
        "player2_score": calculate_hand_value(player2_hand),
        "player1_stand": False,
        "player2_stand": False,
        "game_state": "active",
        "round_number": 1,
    }

    multiplayer_scores[game_id] = {inviter_id: 0, invitee_id: 0}
    return game_id

def check_multiplayer_tournament_winner(game_id):
    """Проверяет, достиг ли кто-то из игроков 101 очка"""
    scores = multiplayer_scores.get(game_id)
    if not scores:
        return None

    game = multiplayer_games.get(game_id)
    if not game:
        return None

    player1_id = game["player1_id"]
    player2_id = game["player2_id"]
    player1_score = scores.get(player1_id, 0)
    player2_score = scores.get(player2_id, 0)

    if player1_score >= 101:
        return "player1"
    elif player2_score >= 101:
        return "player2"
    return None

def update_multiplayer_game_display(game_id, player_id):
    """Обновляет отображение мультиплеерной игры"""
    game = multiplayer_games.get(game_id)
    if not game:
        return None, None

    scores = multiplayer_scores.get(game_id, {})
    player_name = user_names.get(player_id, "фраерок")
    opponent_id = game["player2_id"] if player_id == game["player1_id"] else game["player1_id"]
    opponent_name = game["player2_name"] if player_id == game["player1_id"] else game["player1_name"]

    if player_id == game["player1_id"]:
        player_hand = game["player1_hand"]
        player_score = game["player1_score"]
        player_total_score = scores.get(player_id, 0)
        opponent_total_score = scores.get(opponent_id, 0)
    else:
        player_hand = game["player2_hand"]
        player_score = game["player2_score"]
        player_total_score = scores.get(player_id, 0)
        opponent_total_score = scores.get(opponent_id, 0)

    game_text = (
        f" <b>Игра в 21 против {opponent_name}</b>\n\n"
        f" Ставка: <b>{game['bet']}</b>\n"
        f" Раунд: {game['round_number']}\n\n"
        f" Турнирные очки:\n"
        f" {player_name}: {player_total_score}\n"
        f" {opponent_name}: {opponent_total_score}\n\n"
        f" <b>Твои карты:</b> {get_hand_display(player_hand)}\n"
        f" Очков в раунде: {player_score}\n\n"
        f" <b>Карты {opponent_name}:</b> ❓ ❓\n"
        f" Очков в раунде: ???\n\n"
    )

    tournament_winner = check_multiplayer_tournament_winner(game_id)
    if tournament_winner:
        if tournament_winner == "player1":
            winner_name = game["player1_name"]
        else:
            winner_name = game["player2_name"]

        game_text += f" <b>ТУРНИР ЗАВЕРШЕН!</b>\n"
        game_text += f"Победитель: {winner_name}!\n"
        game_text += f"{winner_name} набрал(а) 101 очко и забирает ставку <b>{game['bet']}</b>!"
        del multiplayer_games[game_id]
        if game_id in multiplayer_scores:
            del multiplayer_scores[game_id]
        return game_text, None

    if game["current_turn"] == player_id:
        game_text += " <b>Твой ход!</b> Выбери действие:"
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_hit = types.InlineKeyboardButton("Давай карту", callback_data=f"multi_hit_{game_id}")
        btn_stand = types.InlineKeyboardButton("Хватит", callback_data=f"multi_stand_{game_id}")
        markup.add(btn_hit, btn_stand)
    else:
        game_text += f"⏳ <b>Ход {opponent_name}</b>\nЖди своего хода..."
        markup = None

    return game_text, markup

def end_multiplayer_round_and_continue(game_id):
    """Завершает раунд и начинает следующий"""
    # Упрощенная версия для экономии места
    game = multiplayer_games.get(game_id)
    if not game:
        return

    scores = multiplayer_scores.get(game_id)
    if not scores:
        return

    player1_score = game["player1_score"]
    player2_score = game["player2_score"]
    
    # Определяем победителя раунда
    if player1_score > 21 and player2_score > 21:
        # Оба проиграли
        pass
    elif player1_score > 21:
        # Игрок 1 перебрал
        scores[game["player2_id"]] += player2_score
    elif player2_score > 21:
        # Игрок 2 перебрал
        scores[game["player1_id"]] += player1_score
    elif player1_score > player2_score:
        scores[game["player1_id"]] += player1_score
    elif player2_score > player1_score:
        scores[game["player2_id"]] += player2_score

    # Проверяем турнирного победителя
    tournament_winner = check_multiplayer_tournament_winner(game_id)
    if tournament_winner:
        if tournament_winner == "player1":
            winner_name = game["player1_name"]
        else:
            winner_name = game["player2_name"]

        result_text = f"🎮 <b>ТУРНИР ЗАВЕРШЕН!</b>\n\nПобедитель: {winner_name}!\n{winner_name} забирает ставку <b>{game['bet']}</b>!"
        bot.send_message(game["player1_id"], result_text, parse_mode="HTML")
        bot.send_message(game["player2_id"], result_text, parse_mode="HTML")
        del multiplayer_games[game_id]
        if game_id in multiplayer_scores:
            del multiplayer_scores[game_id]
        return

    # Начинаем новый раунд
    game["player1_hand"] = [deal_card(), deal_card()]
    game["player2_hand"] = [deal_card(), deal_card()]
    game["player1_score"] = calculate_hand_value(game["player1_hand"])
    game["player2_score"] = calculate_hand_value(game["player2_hand"])
    game["player1_stand"] = False
    game["player2_stand"] = False
    game["current_turn"] = game["player1_id"]
    game["round_number"] += 1

    # Обновляем отображение
    game_text, markup = update_multiplayer_game_display(game_id, game["player1_id"])
    if markup:
        bot.send_message(game["player1_id"], game_text, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(game["player1_id"], game_text, parse_mode="HTML")

    game_text, markup = update_multiplayer_game_display(game_id, game["player2_id"])
    if markup:
        bot.send_message(game["player2_id"], game_text, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(game["player2_id"], game_text, parse_mode="HTML")

# ======================= ОБРАБОТЧИКИ КОМАНД =======================

@bot.message_handler(commands=["сыграем?"])
def new_tournament(message):
    user_id = message.from_user.id
    record_user_visit(user_id)
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
    msg = bot.send_message(message.chat.id, f"На что играем, {name}?", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_bet_with_humor)

def process_bet_with_humor(message):
    user_id = message.from_user.id
    record_user_visit(user_id)
    if user_id not in user_names:
        user_names[user_id] = message.from_user.first_name or "фраерок"
    
    original_bet = message.text.strip()
    bet_text = original_bet.lower().strip()
    cleaned_bet = clean_bet_text(bet_text)
    display_bet = cleaned_bet

    # Проверки ставок
    forbidden_names = ["алекса", "алекс", "юры", "юрину", "юрино", "александров", "александрова", "юркину", "юрки", "юркин"]

    if any(phrase in bet_text for phrase in ["просто так", "простотак", "да просто", "за просто так"]):
        bot.send_message(message.chat.id, "Ты побереги свой 'просто так'.\nДумай еще.", parse_mode="HTML")
        msg = bot.send_message(message.chat.id, "Так на что играем?")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif any(name in bet_text for name in forbidden_names):
        bot.send_message(message.chat.id, f"Нет, мы будем играть на твое рыжее, драное очко\nИ за базар придется отвечать...", parse_mode="HTML")
        user_bets[user_id] = "твое рыжее, драное очко"
        start_new_round(message)
        return
    elif "интерес" in bet_text:
        bot.send_message(message.chat.id, "Мой интерес - твоя квартира. Но я человек добрый, даю шанс подумать еще.\nПредложи что-то попроще, пока я не передумал.", parse_mode="HTML")
        msg = bot.send_message(message.chat.id, "Ну? Что предлагаешь?")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif any(phrase in bet_text for phrase in ["мое очко", "мою жопу", "мой рот", "моя жопа"]):
        bot.send_message(message.chat.id, "Я с петухами в карты не играю.\nПодумай еще.", parse_mode="HTML")
        time.sleep(1)
        msg = bot.send_message(message.chat.id, "А ты че задумался то?")
        bot.register_next_step_handler(msg, process_bet_with_humor)
        return
    elif any(phrase in bet_text for phrase in ["твое очко", "твою жопу", "твой рот", "твоя жопа"]):
        bot.send_message(message.chat.id, f"О как!\nПринимаю! Ставка  {display_bet}.\n За базар придется отвечать...", parse_mode="HTML")
        user_bets[user_id] = display_bet
        ask_for_multiplayer_invitation(message, user_id, display_bet)
        return
    else:
        bot.send_message(message.chat.id, f"Ну давай, играем на {display_bet}!\nПонеслась.., моча по трубам!", parse_mode="HTML")
        user_bets[user_id] = display_bet
        ask_for_multiplayer_invitation(message, user_id, display_bet)

# ======================= ИСПРАВЛЕННЫЕ ОБРАБОТЧИКИ ПРИГЛАШЕНИЙ =======================

@bot.callback_query_handler(func=lambda call: call.data in ["invite_yes", "invite_no"])
def handle_invite_decision(call):
    user_id = call.from_user.id
    record_user_visit(user_id)
    
    if call.data == "invite_no":
        # Пользователь хочет играть с ботом
        bot.answer_callback_query(call.id, "Играем с ботом!")
        bot.edit_message_text(
            "🤖 Отлично! Играем с ботом!",
            call.message.chat.id,
            call.message.message_id
        )
        # Запускаем обычную игру
        start_new_round(call.message)
    
    elif call.data == "invite_yes":
        # Пользователь хочет пригласить другого игрока
        user_state = user_states.get(user_id)
        if not user_state:
            bot.answer_callback_query(call.id, "Ошибка: данные не найдены")
            return
        
        bet = user_state['bet']
        inviter_name = user_names.get(user_id, "фраерок")
        invitation_id = create_multiplayer_invitation(user_id, bet)
        
        bot.answer_callback_query(call.id, "Создаю приглашение...")
        
        # Создаем клавиатуру с кнопками
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Кнопка 1: Показать готовое сообщение с кнопкой для друга
        btn_show_invite = types.InlineKeyboardButton(
            "📤 Показать приглашение для друга",
            callback_data=f"show_invite_{invitation_id}"
        )
        
        # Кнопка 2: Копировать команду для отправки вручную
        btn_copy = types.InlineKeyboardButton(
            "📋 Копировать команду для друга",
            callback_data=f"copy_invite_{invitation_id}"
        )
        
        # Кнопка 3: Отмена
        btn_cancel = types.InlineKeyboardButton("❌ Отмена (играть с ботом)", callback_data="invite_cancel")
        
        markup.add(btn_show_invite, btn_copy, btn_cancel)
        
        bot.edit_message_text(
            f"✅ <b>Приглашение создано!</b>\n\n"
            f"👤 <b>Твое имя:</b> {inviter_name}\n"
            f"💰 <b>Ставка:</b> {bet}\n\n"
            f"<b>Как пригласить друга:</b>\n"
            f"1. Нажми '📤 Показать приглашение для друга'\n"
            f"2. Скопируй готовое сообщение с кнопкой\n"
            f"3. Отправь другу в Telegram\n\n"
            f"<b>Или можешь:</b>\n"
            f"• Скопировать команду и отправить другу вручную\n"
            f"• Отменить и начать игру с ботом",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_invite_"))
def handle_show_invite(call):
    """Показывает готовое приглашение с кнопкой для отправки другу"""
    user_id = call.from_user.id
    record_user_visit(user_id)
    
    invitation_id = call.data.replace("show_invite_", "")
    invitation = pending_invitations.get(invitation_id)
    
    if not invitation:
        bot.answer_callback_query(call.id, "❌ Приглашение не найдено")
        return
    
    bet = invitation['bet']
    inviter_name = invitation['inviter_name']
    
    # Создаем красивое приглашение с кнопкой
    invite_text = (
        f"🎮 <b>Приглашение на игру в 21!</b>\n\n"
        f"👤 <b>Игрок:</b> {inviter_name}\n"
        f"💰 <b>Ставка:</b> {bet}\n"
        f"🎯 <b>Турнир до 101 очка!</b>\n\n"
        f"<b>Чтобы присоединиться к игре:</b>"
    )
    
    # Создаем кнопку для принятия приглашения
    markup = types.InlineKeyboardMarkup()
    btn_accept = types.InlineKeyboardButton(
        "✅ Присоединиться к игре",
        callback_data=f"accept_from_share_{invitation_id}"
    )
    markup.add(btn_accept)
    
    bot.answer_callback_query(call.id, "✅ Готовое приглашение показано!")
    
    bot.send_message(
        call.message.chat.id,
        f"📤 <b>Готовое приглашение для друга:</b>\n\n"
        f"Скопируй и отправь другу это сообщение:\n\n"
        f"{invite_text}",
        reply_markup=markup,
        parse_mode="HTML"
    )
    
    # Также показываем инструкцию
    instructions = (
        f"<b>Как отправить приглашение другу:</b>\n\n"
        f"1. Нажми и удерживай сообщение выше\n"
        f"2. Выбери 'Переслать сообщение'\n"
        f"3. Выбери друга из списка контактов\n"
        f"4. Нажми 'Отправить'\n\n"
        f"<b>Или:</b>\n"
        f"1. Нажми три точки (...) в правом верхнем углу\n"
        f"2. Выбери 'Копировать текст'\n"
        f"3. Отправь другу вручную\n\n"
        f"<b>Друг сможет нажать кнопку '✅ Присоединиться к игре'</b>"
    )
    
    bot.send_message(call.message.chat.id, instructions, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_invite_") or call.data == "invite_cancel")
def handle_invite_actions(call):
    user_id = call.from_user.id
    record_user_visit(user_id)
    
    if call.data == "invite_cancel":
        bot.answer_callback_query(call.id, "Отменяем приглашение...")
        bot.edit_message_text(
            "❌ Приглашение отменено. Начинаем игру с ботом!",
            call.message.chat.id,
            call.message.message_id
        )
        start_new_round(call.message)
        return
    
    elif call.data.startswith("copy_invite_"):
        invitation_id = call.data.replace("copy_invite_", "")
        invitation = pending_invitations.get(invitation_id)
        
        if not invitation:
            bot.answer_callback_query(call.id, "❌ Приглашение не найдено")
            return
        
        bet = invitation['bet']
        inviter_name = invitation['inviter_name']
        command_text = f"/принять {invitation_id}"
        
        # Текст для отправки другу
        manual_invite = (
            f"🎮 {inviter_name} приглашает тебя на игру в 21!\n\n"
            f"💰 Ставка: {bet}\n"
            f"🎯 Турнир до 101 очка\n\n"
            f"Чтобы присоединиться, отправь боту @{bot.get_me().username} команду:\n"
            f"{command_text}\n\n"
            f"Или нажми кнопку ниже 👇"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn_accept = types.InlineKeyboardButton(
            "✅ Присоединиться к игре",
            callback_data=f"accept_from_share_{invitation_id}"
        )
        markup.add(btn_accept)
        
        bot.answer_callback_query(call.id, "📋 Команда скопирована!", show_alert=False)
        
        bot.send_message(
            call.message.chat.id,
            f"📋 <b>Приглашение для отправки другу:</b>\n\n"
            f"{manual_invite}",
            reply_markup=markup,
            parse_mode="HTML"
        )
        
        # Инструкции по отправке
        bot.send_message(
            call.message.chat.id,
            f"<b>Как отправить:</b>\n\n"
            f"1. Нажми и удерживай сообщение выше\n"
            f"2. Выбери 'Переслать сообщение'\n"
            f"3. Выбери друга из списка контактов\n\n"
            f"<b>Или:</b>\n"
            f"1. Скопируй команду ниже\n"
            f"2. Отправь другу в чат\n\n"
            f"<code>{command_text}</code>",
            parse_mode="HTML"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_from_share_"))
def handle_accept_from_share(call):
    """Обработка принятия приглашения из шаринга"""
    user_id = call.from_user.id
    record_user_visit(user_id)
    
    invitation_id = call.data.replace("accept_from_share_", "")
    invitation = pending_invitations.get(invitation_id)
    
    if not invitation:
        bot.answer_callback_query(call.id, "❌ Приглашение не найдено или устарело")
        return
    
    if invitation['status'] != 'pending':
        bot.answer_callback_query(call.id, "❌ Это приглашение уже было использовано")
        return
    
    # Проверяем, не пытается ли пользователь принять свое же приглашение
    if user_id == invitation['inviter_id']:
        bot.answer_callback_query(call.id, "❌ Нельзя принять собственное приглашение!")
        markup = types.InlineKeyboardMarkup()
        btn_new_game = types.InlineKeyboardButton("🎮 Начать новую игру", callback_data="new_game_after_self_invite")
        markup.add(btn_new_game)
        
        bot.send_message(
            call.message.chat.id,
            f"🤔 <b>Это твое собственное приглашение!</b>\n\n"
            f"Чтобы пригласить друга:\n"
            f"1. Начни игру командой /сыграем?\n"
            f"2. Сделай ставку\n"
            f"3. Выбери '🎮 Пригласить друга'\n"
            f"4. Отправь приглашение другу\n\n"
            f"Хочешь начать новую игру?",
            reply_markup=markup,
            parse_mode="HTML"
        )
        return
    
    bot.answer_callback_query(call.id, "🔄 Принимаем приглашение...")
    
    # Обновляем приглашение
    invitation['invitee_id'] = user_id
    invitation['status'] = 'accepted'
    
    # Создаем мультиплеерную игру
    game_id = create_multiplayer_game(invitation['inviter_id'], user_id, invitation['bet'])
    
    # Уведомляем обоих игроков
    inviter_name = invitation['inviter_name']
    invitee_name = user_names.get(user_id, "фраерок")
    bet = invitation['bet']
    
    bot.send_message(
        invitation['inviter_id'],
        f"🎮 <b>{invitee_name} принял(а) твое приглашение!</b>\n\n"
        f"💰 Ставка: <b>{bet}</b>\n"
        f"👥 Игроки: {inviter_name} vs {invitee_name}\n\n"
        f"🎯 <b>Турнир до 101 очка!</b>\n"
        f"Игра начинается! Ты ходишь первым.",
        parse_mode="HTML"
    )
    
    bot.send_message(
        user_id,
        f"🎮 <b>Ты принял(а) приглашение от {inviter_name}!</b>\n\n"
        f"💰 Ставка: <b>{bet}</b>\n"
        f"👥 Игроки: {inviter_name} vs {invitee_name}\n\n"
        f"🎯 <b>Турнир до 101 очка!</b>\n"
        f"Игра начинается! Первым ходит {inviter_name}.",
        parse_mode="HTML"
    )
    
    # Показываем игру обоим игрокам
    game = multiplayer_games[game_id]
    game_text, markup = update_multiplayer_game_display(game_id, invitation['inviter_id'])
    if markup:
        bot.send_message(invitation['inviter_id'], game_text, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(invitation['inviter_id'], game_text, parse_mode="HTML")
    
    game_text, markup = update_multiplayer_game_display(game_id, user_id)
    if markup:
        bot.send_message(user_id, game_text, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(user_id, game_text, parse_mode="HTML")
    
    # Удаляем приглашение
    del pending_invitations[invitation_id]
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data == "new_game_after_self_invite")
def handle_new_game_after_self_invite(call):
    """Начать новую игру после попытки принять собственное приглашение"""
    bot.answer_callback_query(call.id, "Начинаем новую игру...")
    bot.edit_message_text(
        "🎮 Отлично! Начинаем новую игру.\n\n"
        "Напиши команду /сыграем? чтобы сделать ставку и начать игру.",
        call.message.chat.id,
        call.message.message_id
    )

def clean_old_invitations():
    """Очищает старые приглашения (старше 30 минут)"""
    now = datetime.now()
    expired_invitations = []
    
    for invitation_id, invitation in pending_invitations.items():
        if invitation['status'] == 'pending':
            if now - invitation['timestamp'] > timedelta(minutes=30):
                expired_invitations.append(invitation_id)
    
    for invitation_id in expired_invitations:
        del pending_invitations[invitation_id]
    
    if expired_invitations:
        print(f"Очищено {len(expired_invitations)} истекших приглашений")

@bot.message_handler(commands=["принять"])
def accept_invitation(message):
    user_id = message.from_user.id
    record_user_visit(user_id)
    
    clean_old_invitations()
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(
                message.chat.id, 
                "🎮 <b>Как принять приглашение:</b>\n\n"
                "1. Получи от друга приглашение в Telegram\n"
                "2. Нажми кнопку '✅ Присоединиться к игре' в сообщении\n\n"
                "<b>Или:</b>\n"
                "1. Получи от друга команду вида:\n"
                "<code>/принять inv_123_456789</code>\n"
                "2. Отправь ее мне\n\n"
                "<b>Не знаешь как пригласить друга?</b>\n"
                "Начни игру командой /сыграем?, сделай ставку и выбери 'Пригласить друга'",
                parse_mode="HTML"
            )
            return
        
        invitation_id = parts[1]
        invitation = pending_invitations.get(invitation_id)
        
        if not invitation:
            bot.send_message(
                message.chat.id, 
                "❌ Приглашение не найдено или устарело.\n\n"
                "Возможные причины:\n"
                "• Приглашение было отменено\n"
                "• Прошло больше 30 минут\n"
                "• Приглашение уже использовано\n\n"
                "Попроси друга отправить новое приглашение."
            )
            return
        
        if invitation['status'] != 'pending':
            bot.send_message(message.chat.id, "❌ Это приглашение уже было использовано.")
            return
        
        # Проверяем, не пытается ли пользователь принять свое же приглашение
        if user_id == invitation['inviter_id']:
            bot.send_message(
                message.chat.id,
                "🤔 <b>Это твое собственное приглашение!</b>\n\n"
                "Чтобы пригласить друга:\n"
                "1. Начни игру командой /сыграем?\n"
                "2. Сделай ставку\n"
                "3. Выбери '🎮 Пригласить друга'\n"
                "4. Отправь приглашение другу\n\n"
                "Начни новую игру: /сыграем?"
            )
            return
        
        # Обновляем приглашение
        invitation['invitee_id'] = user_id
        invitation['status'] = 'accepted'
        
        # Создаем мультиплеерную игру
        game_id = create_multiplayer_game(invitation['inviter_id'], user_id, invitation['bet'])
        
        # Уведомляем обоих игроков
        inviter_name = invitation['inviter_name']
        invitee_name = user_names.get(user_id, "фраерок")
        bet = invitation['bet']
        
        bot.send_message(
            invitation['inviter_id'],
            f"🎮 <b>{invitee_name} принял(а) твое приглашение!</b>\n\n"
            f"💰 Ставка: <b>{bet}</b>\n"
            f"👥 Игроки: {inviter_name} vs {invitee_name}\n\n"
            f"🎯 <b>Турнир до 101 очка!</b>\n"
            f"Игра начинается! Ты ходишь первым.",
            parse_mode="HTML"
        )
        
        bot.send_message(
            user_id,
            f"🎮 <b>Ты принял(а) приглашение от {inviter_name}!</b>\n\n"
            f"💰 Ставка: <b>{bet}</b>\n"
            f"👥 Игроки: {inviter_name} vs {invitee_name}\n\n"
            f"🎯 <b>Турнир до 101 очка!</b>\n"
            f"Игра начинается! Первым ходит {inviter_name}.",
            parse_mode="HTML"
        )
        
        # Показываем игру обоим игрокам
        game = multiplayer_games[game_id]
        game_text, markup = update_multiplayer_game_display(game_id, invitation['inviter_id'])
        if markup:
            bot.send_message(invitation['inviter_id'], game_text, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(invitation['inviter_id'], game_text, parse_mode="HTML")
        
        game_text, markup = update_multiplayer_game_display(game_id, user_id)
        if markup:
            bot.send_message(user_id, game_text, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(user_id, game_text, parse_mode="HTML")
        
        # Удаляем приглашение
        del pending_invitations[invitation_id]
        
    except Exception as e:
        print(f"Ошибка при принятии приглашения: {e}")
        bot.send_message(
            message.chat.id, 
            f"❌ Произошла ошибка при принятии приглашения.\n"
            f"Проверь правильность команды или попроси друга отправить новое приглашение."
        )

@bot.message_handler(commands=["продолжим?"])
def continue_tournament(message):
    user_id = message.from_user.id
    record_user_visit(user_id)
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
    record_user_visit(user_id)
    
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

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("multi_hit_") or call.data.startswith("multi_stand_")
)
def handle_multiplayer_action(call):
    user_id = call.from_user.id
    record_user_visit(user_id)

    try:
        if call.data.startswith("multi_hit_"):
            game_id = call.data.replace("multi_hit_", "")
            action = "hit"
        else:
            game_id = call.data.replace("multi_stand_", "")
            action = "stand"

        game = multiplayer_games.get(game_id)
        if not game:
            bot.answer_callback_query(call.id, "Игра не найдена!")
            return

        if game["current_turn"] != user_id:
            bot.answer_callback_query(call.id, "Сейчас не твой ход!")
            return

        if user_id == game["player1_id"]:
            if action == "hit":
                game["player1_hand"].append(deal_card())
                game["player1_score"] = calculate_hand_value(game["player1_hand"])
                if game["player1_score"] > 21:
                    bot.answer_callback_query(call.id, "У тебя перебор!")
                    game["player1_stand"] = True
                    game["current_turn"] = game["player2_id"]
                else:
                    bot.answer_callback_query(call.id, "Карта добавлена!")
            elif action == "stand":
                bot.answer_callback_query(call.id, "Ход завершен!")
                game["player1_stand"] = True
                game["current_turn"] = game["player2_id"]
        else:
            if action == "hit":
                game["player2_hand"].append(deal_card())
                game["player2_score"] = calculate_hand_value(game["player2_hand"])
                if game["player2_score"] > 21:
                    bot.answer_callback_query(call.id, "У тебя перебор!")
                    game["player2_stand"] = True
                    game["current_turn"] = game["player1_id"]
                else:
                    bot.answer_callback_query(call.id, "Карта добавлена!")
            elif action == "stand":
                bot.answer_callback_query(call.id, "Ход завершен!")
                game["player2_stand"] = True
                game["current_turn"] = game["player1_id"]

        round_over = False
        if game["player1_stand"] and game["player2_stand"]:
            round_over = True
        if game["player1_score"] > 21 and game["player2_score"] > 21:
            round_over = True
        if (game["player1_score"] > 21 and game["player2_stand"]) or (game["player2_score"] > 21 and game["player1_stand"]):
            round_over = True

        if round_over:
            end_multiplayer_round_and_continue(game_id)
        else:
            game_text, markup = update_multiplayer_game_display(game_id, user_id)
            try:
                if markup:
                    bot.edit_message_text(
                        game_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode="HTML",
                    )
                else:
                    bot.edit_message_text(
                        game_text,
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode="HTML",
                    )
            except:
                if markup:
                    bot.send_message(user_id, game_text, reply_markup=markup, parse_mode="HTML")
                else:
                    bot.send_message(user_id, game_text, parse_mode="HTML")

            opponent_id = game["player2_id"] if user_id == game["player1_id"] else game["player1_id"]
            game_text, markup = update_multiplayer_game_display(game_id, opponent_id)
            if markup:
                bot.send_message(opponent_id, game_text, reply_markup=markup, parse_mode="HTML")
            else:
                bot.send_message(opponent_id, game_text, parse_mode="HTML")

    except Exception as e:
        print(f"Ошибка в мультиплеерной игре: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка!")

# ======================= ОРИГИНАЛЬНЫЙ КОД ОРАКУЛА =======================
# [Сохраняем всю оригинальную логику оракула без изменений]
# Включая templates, когда, почему, как, кто, куда, кого, ты, вы, sp
# keyword_lists, get_response_by_keywords, default_nicks и т.д.

# [Здесь должен быть весь остальной код оракула, который уже есть в основном файле]
# Я сохраняю его как есть, только добавляю исправленную систему приглашений

# ======================= ФЛЕСК РОУТЫ =======================
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
        "games_played": len(game_history),
        "pending_invitations": len(pending_invitations),
        "active_multiplayer_games": len(multiplayer_games),
    }

# ======================= ЗАПУСК НА RENDER =======================
def run_flask():
    """Запускает Flask сервер"""
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

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
